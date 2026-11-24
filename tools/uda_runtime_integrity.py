"""Source-bound staged runtime inventory and disposable replacement rehearsal.

Never installs into production. Only explicit installer payload files are
included; config, venv, caches and live state are not replacement payloads.
The manifest is evidence, not a signature or release authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def payload_paths(source: Path) -> dict[str, Path]:
    script = (source / "install.sh").read_text()
    direct = set(re.findall(r'"\$SOURCE_DIR/([A-Za-z0-9_./-]+)"', script))
    block = script.split("for module in ", 1)[1].split("\ndo\n", 1)[0]
    direct.update(re.findall(r"[A-Za-z0-9_]+\.py", block))
    result = {}
    for name in sorted(direct):
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe payload path")
        if path.suffix == ".py" or path.parts[0] in {"templates", "schemas", "static"}:
            result["runtime/" + name] = source / path
        elif path.parts[0] == "systemd":
            result["units/" + path.name] = source / path
        elif name not in {"requirements.txt", "config.example.json"}:
            raise ValueError("Unexpected installer source")
    result["bin/uda-trigger-ci"] = source / "github_ci.py"
    if len(result) < 40 or "runtime/dashboard.py" not in result:
        raise ValueError("Incomplete installer inventory")
    return result


def regular_file(root: Path, relative: str) -> Path:
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Symlink in payload")
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Missing or unsafe payload file")
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(stage: Path, source: Path = ROOT) -> dict:
    if stage.is_symlink() or not stage.is_dir():
        raise ValueError("Stage must be a real directory")
    if stage.stat().st_uid != os.getuid() or stat.S_IMODE(stage.stat().st_mode) != 0o700:
        raise ValueError("Stage must be owner-private")
    paths = payload_paths(source)
    files = {}
    for relative, original in paths.items():
        original = regular_file(source, str(original.relative_to(source)))
        staged = regular_file(stage, relative)
        expected = digest(original)
        if digest(staged) != expected:
            raise ValueError("Staged payload differs from source: " + relative)
        mode = stat.S_IMODE(staged.stat().st_mode)
        if mode not in {0o644, 0o755}:
            raise ValueError("Unexpected staged file mode: " + relative)
        files[relative] = {"sha256": expected, "mode": mode, "size": staged.stat().st_size}
    return {"files": files, "payload_count": len(files),
            "source_bytes_verified": True, "production_upgrade_authorized": False}


def rehearse(stage: Path, source: Path = ROOT) -> dict:
    manifest = inventory(stage, source)
    entries = manifest["files"]
    with tempfile.TemporaryDirectory(prefix="uda-runtime-rehearsal-") as folder:
        lab = Path(folder)
        target = lab / "synthetic-installed"
        target.mkdir()
        backup = lab / "backup"
        backup.mkdir()
        # Synthetic old files only. Include a new-file case and an unmanaged sentinel.
        existing = set(entries) - {sorted(entries)[0]}
        for name in existing:
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic previous release: " + name)
            path.chmod(0o600)
        sentinel = target / "unmanaged-state"
        sentinel.write_text("preserve")
        for name in existing:
            path = backup / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target / name, path)
        before = {name: (digest(target / name), stat.S_IMODE((target / name).stat().st_mode))
                  for name in existing}
        applied = []
        injected = False
        try:
            for name, item in entries.items():
                dest = target / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                candidate = dest.with_name(dest.name + ".candidate")
                shutil.copyfile(regular_file(stage, name), candidate)
                candidate.chmod(item["mode"])
                if digest(candidate) != item["sha256"]:
                    raise ValueError("Candidate integrity failure")
                os.replace(candidate, dest)
                applied.append(name)
                if len(applied) == max(2, len(entries) // 2):
                    injected = True
                    raise RuntimeError("Synthetic installation failure")
        except RuntimeError:
            if not injected:
                raise
        finally:
            for name in reversed(applied):
                dest = target / name
                if name in existing:
                    shutil.copy2(backup / name, dest)
                else:
                    dest.unlink()
        restored = all((digest(target / n), stat.S_IMODE((target / n).stat().st_mode)) == v
                       for n, v in before.items())
        new_absent = all(not (target / n).exists() for n in set(entries) - existing)
        if not (injected and restored and new_absent and sentinel.read_text() == "preserve"):
            raise RuntimeError("Disposable rollback verification failed")
    return {"status": "PASS", "payload_count": len(entries),
            "source_bytes_verified": True, "synthetic_failure_injected": True,
            "previous_bytes_and_modes_restored": True, "new_files_removed": True,
            "unmanaged_state_preserved": True, "production_files_modified": False,
            "systemctl_invoked": False, "production_upgrade_authorized": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inventory", "rehearse"])
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (inventory if args.action == "inventory" else rehearse)(args.stage)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
