"""Read-only UDA installed-file release inventory.

This is an evidence collector, not an installer, a backup or deployment
approval. Only allowlisted application files are inspected; protected config
contents and hashes are NEVER read. Output intentionally excludes real paths,
account names, tokens, and arbitrary directory listings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

DEFAULT_RUNTIME = Path("~/.local/share/deployment-agent").expanduser()
DEFAULT_CONFIG = Path("~/.config/deployment-agent/config.json").expanduser()

# Minimal, stable evidence surface. Never recurse through the runtime's venv,
# config, registry, SQLite databases, or arbitrary application directories.
RUNTIME_FILES = (
    "deploy_agent.py",
    "dashboard.py",
    "approval_centre.py",
    "approval_identity.py",
    "deployment_reporting.py",
    "onboarding_v2.py",
    "uda_manifest_v2_validate.py",
    "templates/dashboard.html",
    "templates/approvals.html",
    "templates/onboarding.html",
    "schemas/uda-manifest-v2.schema.json",
    "tools/validate_v2_only.py",
    "tools/v2_design_holds.py",
    "tools/validate_v2_fleet.py",
)
MAX_HASH_BYTES = 2 * 1024 * 1024


def _safe_file(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    try:
        # Explicitly reject symlinks in the full relative path, including the
        # top-level installed runtime directory and nested subdirectories.
        parent = root
        for component in (".", *Path(relative).parts):
            if component != ".":
                parent = parent / component
            if stat.S_ISLNK(parent.lstat().st_mode):
                return {"file": relative, "status": "symlink_refused"}
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode):
            return {"file": relative, "status": "not_regular"}
        if metadata.st_size > MAX_HASH_BYTES:
            return {"file": relative, "status": "oversized"}
        digest = hashlib.sha256()
        # Never follow symlink if it is swapped during inspection.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_HASH_BYTES:
                return {"file": relative, "status": "changed_or_oversized"}
            for block in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(block)
            if opened.st_dev != metadata.st_dev or opened.st_ino != metadata.st_ino:
                return {"file": relative, "status": "changed_during_scan"}
        return {
            "file": relative, "status": "present",
            "sha256": digest.hexdigest(), "size": metadata.st_size,
            "group_writable": bool(metadata.st_mode & stat.S_IWGRP),
            "world_writable": bool(metadata.st_mode & stat.S_IWOTH),
        }
    except (OSError, ValueError):
        return {"file": relative, "status": "unavailable"}


def _config_metadata(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            return {"status": "not_regular_or_symlink"}
        mode = stat.S_IMODE(metadata.st_mode)
        return {
            "status": "present",
            "owner_readable": bool(mode & stat.S_IRUSR),
            "group_accessible": bool(mode & (stat.S_IRWXG)),
            "world_accessible": bool(mode & (stat.S_IRWXO)),
            "mode_octal": f"{mode:04o}",
        }
    except OSError:
        return {"status": "unavailable"}


def collect(*, runtime: Path = DEFAULT_RUNTIME,
            config: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    """Inspect only allowlisted runtime files and config file stat metadata."""
    try:
        root_meta = runtime.lstat()
        root_status = (
            "directory" if stat.S_ISDIR(root_meta.st_mode) else "not_directory"
        )
        root_group_writable = bool(root_meta.st_mode & stat.S_IWGRP)
        root_world_writable = bool(root_meta.st_mode & stat.S_IWOTH)
    except OSError:
        root_status = "unavailable"
        root_group_writable = False
        root_world_writable = False

    files = [_safe_file(runtime, relative) if root_status == "directory"
             else {"file": relative, "status": "unavailable"}
             for relative in RUNTIME_FILES]
    cfg = _config_metadata(config)
    issues = []
    if root_status != "directory":
        issues.append("runtime_not_regular_directory")
    if root_group_writable or root_world_writable:
        issues.append("runtime_directory_writable_by_others")
    if any(f["status"] != "present" for f in files):
        issues.append("runtime_files_missing_or_unreadable")
    if any(f.get("group_writable") or f.get("world_writable") for f in files):
        issues.append("runtime_file_writable_by_others")
    if cfg["status"] != "present":
        issues.append("config_metadata_unavailable")
    elif cfg["group_accessible"] or cfg["world_accessible"]:
        issues.append("config_permissions_too_broad")
    return {
        "evidence_kind": "read_only_installed_file_metadata",
        "runtime_status": root_status,
        "runtime_group_writable": root_group_writable,
        "runtime_world_writable": root_world_writable,
        "files": files,
        "protected_config": cfg,
        "issues_for_operator_review": issues,
        "runtime_complete": root_status == "directory" and all(
            f["status"] == "present" for f in files),
        "backup_verified": False,
        "rollback_verified": False,
        "production_upgrade_authorized": False,
        "operator_note": (
            "Hashes are observational only and are not an installer identity. "
            "No files were modified and protected config content was not read."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    report = collect(runtime=args.runtime, config=args.config)
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if not report["issues_for_operator_review"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
