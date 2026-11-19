"""Offline release assembly for repository onboarding.

Prepare a content-addressed release and systemd *preview*, without activating
the release, executing application code, or modifying production configuration.
The separate activation phase must verify privileges, health and rollback.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from onboarding import OnboardingError
from onboarding_install import SHA40

SAFE_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _root(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise OnboardingError("Managed root cannot be a symlink")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_dir():
        raise OnboardingError("Managed root is not a directory")
    return resolved


def _stage_source(staged: dict, stage_root: Path) -> tuple[Path, str, str]:
    root = _root(stage_root)
    name = staged.get("application")
    sha = staged.get("commit_sha")
    if not isinstance(name, str) or not SAFE_SLUG.fullmatch(name):
        raise OnboardingError("Invalid application identity")
    if not isinstance(sha, str) or not SHA40.fullmatch(sha):
        raise OnboardingError("Invalid source SHA")
    expected = root / f"{name}-{sha[:12]}"
    source = staged.get("staged_path")
    if not isinstance(source, str) or Path(source).resolve() != expected:
        raise OnboardingError("Staged path is not an approved child of staging root")
    if expected.is_symlink() or not expected.is_dir():
        raise OnboardingError("Missing verified staged source")
    return expected, name, sha


def _safe_file_tree(source: Path) -> list[Path]:
    """Refuse symlinks, special files and Git internals; bound file count/size."""
    items: list[Path] = []
    total_size = 0
    for directory, dirs, names in os.walk(source, followlinks=False):
        for part in [*dirs, *names]:
            path = Path(directory) / part
            relative = path.relative_to(source)
            if relative.parts[0] == ".git":
                continue
            if path.is_symlink():
                raise OnboardingError("Symbolic links cannot be packaged automatically")
            if path.is_dir():
                continue
            if not path.is_file():
                raise OnboardingError("Special filesystem entries are not supported")
            size = path.stat().st_size
            total_size += size
            items.append(relative)
            if len(items) > 20000 or total_size > 500 * 1024 * 1024:
                raise OnboardingError("Source exceeds safe packaging limits")
    return sorted(items, key=lambda x: x.as_posix())


def _files_manifest(source: Path, files: list[Path]) -> list[dict]:
    manifest = []
    for path in files:
        digest = hashlib.sha256()
        with (source / path).open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        manifest.append({"path": path.as_posix(), "sha256": digest.hexdigest()})
    return manifest


def prepare_release(staged: dict, stage_root: Path, releases_root: Path) -> dict:
    """Copy reviewed source to a never-overwritten release directory.

    No build, dependency installation, service or Caddy mutation occurs.
    """
    source, name, sha = _stage_source(staged, stage_root)
    root = _root(releases_root)
    if root == source or root.is_relative_to(source) or source.is_relative_to(root):
        raise OnboardingError("Release root and staging tree must be separate")
    release = root / name / sha
    if release.exists() or release.is_symlink():
        raise OnboardingError("Release already prepared; refusing overwrite")
    files = _safe_file_tree(source)
    if not files:
        raise OnboardingError("Staged source has no deployable files")
    parent = root / name
    parent.mkdir(mode=0o700, exist_ok=True)
    if parent.is_symlink() or not parent.is_dir():
        raise OnboardingError("Release parent must be a real directory")
    scratch = Path(tempfile.mkdtemp(prefix=".prepare-", dir=parent))
    try:
        for relative in files:
            src, dst = source / relative, scratch / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst, follow_symlinks=False)
            # No setuid or executable permission inherited from untrusted source.
            dst.chmod(0o600)
        content = {"repository": staged["repository"], "application": name,
                   "commit_sha": sha, "files": _files_manifest(scratch, files)}
        receipt = scratch / ".uda-release.json"
        if receipt.exists():
            raise OnboardingError("Repository file conflicts with UDA release receipt")
        receipt.write_text(json.dumps(content, sort_keys=True, indent=2) + "\n")
        receipt.chmod(0o600)
        # Ensure all files copied; no live release has been switched.
        os.replace(scratch, release)
    except Exception:
        if scratch.exists():
            shutil.rmtree(scratch)
        raise
    return {"application": name, "commit_sha": sha, "release_path": str(release),
            "file_count": len(files), "status": "prepared_inactive",
            "registry_modified": False, "service_started": False}


def systemd_unit_preview(plan: dict, release_path: Path, *, environment_file: Path) -> str:
    """Generate display-only unit text; never install or run it."""
    name = plan.get("application")
    if not isinstance(name, str) or not SAFE_SLUG.fullmatch(name):
        raise OnboardingError("Invalid service name")
    if plan.get("service_unit") != f"uda-{name}.service":
        raise OnboardingError("Unexpected service unit")
    port = plan.get("port")
    if type(port) is not int or not 1024 <= port <= 65535:
        raise OnboardingError("An allocated port is required")
    entry = plan.get("entrypoint_pending_approval")
    if not isinstance(entry, list) or not entry or len(entry) > 30:
        raise OnboardingError("Service entrypoint must be reviewed")
    def quote(value):
        if not isinstance(value, str) or not value or any(ch in value for ch in "\x00\r\n"):
            raise OnboardingError("Invalid service argument")
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
    working = release_path.resolve(strict=True)
    secrets = environment_file.expanduser()
    if secrets.is_symlink() or not secrets.is_absolute():
        raise OnboardingError("Environment path must be an absolute non-symlink")
    return "\n".join([
        "# UDA installation PREVIEW ONLY; NOT activated",
        "[Unit]", f"Description=UDA {name}", "After=network.target", "",
        "[Service]", "Type=simple",
        f"WorkingDirectory={quote(str(working))}",
        f"EnvironmentFile={quote(str(secrets))}",
        f"Environment=PORT={port}",
        "ExecStart=" + " ".join(quote(x) for x in entry),
        "NoNewPrivileges=yes", "PrivateTmp=yes",
        "ProtectSystem=strict", "ProtectHome=read-only",
        "Restart=on-failure", "",
        "[Install]", "WantedBy=default.target", "",
    ])


def verify_prepared_release(release_path: Path, expected_sha: str) -> dict:
    """Re-hash every tracked release file and reject additions before activation."""
    path = release_path.expanduser()
    if path.is_symlink() or not path.is_dir():
        raise OnboardingError("Missing or linked release directory")
    if not isinstance(expected_sha, str) or not SHA40.fullmatch(expected_sha):
        raise OnboardingError("Invalid expected release identity")
    receipt = path / ".uda-release.json"
    if receipt.is_symlink() or not receipt.is_file():
        raise OnboardingError("Release receipt is missing")
    try:
        data = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OnboardingError("Release receipt is unreadable") from exc
    if data.get("commit_sha") != expected_sha:
        raise OnboardingError("Release identity does not match approved commit")
    expected = data.get("files")
    if not isinstance(expected, list) or not expected:
        raise OnboardingError("Release manifest is empty or corrupt")
    actual_paths = _safe_file_tree(path)
    actual_names = {p.as_posix() for p in actual_paths if p.as_posix() != ".uda-release.json"}
    expected_names = {row.get("path") for row in expected if isinstance(row, dict)}
    if len(expected_names) != len(expected) or actual_names != expected_names:
        raise OnboardingError("Release file set changed after preparation")
    hashes = {row["path"]: row["sha256"] for row in expected}
    for row in _files_manifest(path, [Path(p) for p in sorted(actual_names)]):
        if row["sha256"] != hashes[row["path"]]:
            raise OnboardingError("Release file checksum mismatch")
    return {"verified": True, "commit_sha": expected_sha,
            "application": data["application"], "file_count": len(actual_names)}
