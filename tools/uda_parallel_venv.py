"""Disposable parallel-venv switching rehearsal; no live destination option.

Build each environment at its permanent location. The old directory is
temporarily renamed only while isolated; its original path is restored
before any old interpreter is invoked. Never execute the moved old venv.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from tools import uda_install_journal as journal
from tools.uda_stage_admission import SMOKE
from tools.uda_runtime_integrity import inventory


def layout(root):
    return root / "venv", root / "venv-v1-retained", root / "venv-v2"


def validate(root):
    if root.is_symlink() or not root.is_dir() or root.stat().st_uid != os.getuid():
        raise ValueError("Unsafe rehearsal root")
    if root.stat().st_mode & 0o777 != 0o700 or not root.name.startswith("uda-venv-lab-"):
        raise ValueError("Private disposable rehearsal required")


def state(root):
    live, old, new = layout(root)
    # A directory is identified by a marker created inside the disposable
    # environment, never by executing an interpreter at its renamed path.
    def kind(path):
        if path.is_symlink():
            if path == live and os.readlink(path) == "venv-v2":
                return "candidate_link"
            raise ValueError("Unexpected symlink")
        if not path.exists():
            return "absent"
        if not path.is_dir():
            raise ValueError("Unexpected environment object")
        marker = path / ".uda-fixture"
        if marker.is_symlink():
            raise ValueError("Unexpected marker")
        value = marker.read_text()
        if value not in {"old", "new"}:
            raise ValueError("Unexpected environment identity")
        return value
    return tuple(kind(p) for p in (live, old, new))


def switch(root, *, interrupt=None):
    validate(root)
    if state(root) != ("old", "absent", "new") or (root / "journal.json").exists():
        raise ValueError("Unexpected initial layout")
    journal.save(root, {"phase": "switching", "version": 1})
    live, old, _ = layout(root)
    live.rename(old)
    journal.sync_dir(root)
    if interrupt:
        interrupt("after_rename")
    live.symlink_to("venv-v2")
    journal.sync_dir(root)
    if interrupt:
        interrupt("after_link")
    if state(root) != ("candidate_link", "old", "new"):
        raise RuntimeError("Switch verification failed")
    journal.save(root, {"phase": "switched", "version": 1})


def restore(root):
    validate(root)
    record = journal.load(root)
    if record.get("version") != 1 or record.get("phase") not in {"switching", "switched", "restoring", "restored"}:
        raise ValueError("Unexpected journal")
    current = state(root)
    allowed = {("old", "absent", "new"), ("absent", "old", "new"),
               ("candidate_link", "old", "new")}
    if current not in allowed:
        raise ValueError("Unexpected environment layout")
    journal.save(root, {"phase": "restoring", "version": 1})
    live, old, _ = layout(root)
    if current[0] == "candidate_link":
        live.unlink()
        journal.sync_dir(root)
    if old.exists():
        old.rename(live)
        journal.sync_dir(root)
    if state(root) != ("old", "absent", "new"):
        raise RuntimeError("Restore verification failed")
    journal.save(root, {"phase": "restored", "version": 1})


def rehearse(stage: Path):
    manifest = inventory(stage)
    with tempfile.TemporaryDirectory(prefix="uda-venv-lab-") as directory:
        root = Path(directory)
        live, _, new = layout(root)
        env = {"HOME": directory, "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
               "PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
        def run(args):
            result = subprocess.run([str(x) for x in args], env=env, cwd=root,
                                    capture_output=True, text=True, timeout=180, check=False)
            if result.returncode:
                raise RuntimeError("Rehearsal command failed: " + str(args[0]) +
                                   " exit " + str(result.returncode))
            return result.stdout.strip()
        # Both venvs use the same base interpreter as the staged installation.
        base = run([stage / "runtime/venv/bin/python", "-I", "-B", "-c",
                    "import sys; print(sys._base_executable)"])
        for path, marker in ((live, "old"), (new, "new")):
            run([base, "-m", "venv", path])
            journal.durable_write(path / ".uda-fixture", marker.encode())
        requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
        run([new / "bin/python", "-I", "-B", "-m", "pip", "install", "-r", requirements])
        config = root / "config.json"
        journal.durable_write(config, json.dumps({"dashboard_token": "fixture-only",
                             "applications": [], "identity_db": str(root / "identity.db")}).encode())
        def prefix():
            return Path(run([live / "bin/python", "-I", "-B", "-c",
                             "import sys; print(sys.prefix)"])).resolve()
        def smoke():
            run([live / "bin/python", "-I", "-B", "-m", "pip", "check"])
            return json.loads(run([live / "bin/python", "-I", "-B", "-c", SMOKE,
                                   stage / "runtime", config]))["smoke"] == "PASS"
        if prefix() != live:
            raise RuntimeError("Original interpreter mismatch")
        switch(root)
        if prefix() != new or not smoke():
            raise RuntimeError("Candidate interpreter or smoke mismatch")
        restore(root)
        if prefix() != live:
            raise RuntimeError("Original interpreter not restored")
        run([live / "bin/python", "-I", "-B", "-m", "pip", "check"])
        if inventory(stage) != manifest:
            raise RuntimeError("Stage changed")
        return {"status": "PASS", "python": run([live / "bin/python", "--version"]),
                "candidate_smoke_passed": True, "original_path_restored": True,
                "production_files_modified": False, "systemctl_invoked": False,
                "production_upgrade_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(rehearse(args.stage.absolute()), indent=2))


if __name__ == "__main__":
    main()
