#!/usr/bin/env python3
"""Explicit, offline-first SQLite approval store backup and disposable restore drill.

Does not replace a production DB, change service settings, or run a privileged
deployment operation. Only writes NEW 0600 files in pre-existing private dirs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys

from tools.approval_store_preflight import inspect_store


def _private_directory(parent: Path) -> None:
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("Destination directory must exist and cannot be a symlink")
    mode = parent.stat()
    if not stat.S_ISDIR(mode.st_mode) or mode.st_mode & 0o077:
        raise ValueError("Destination directory must be private (0700)")
    if mode.st_uid != os.getuid():
        raise ValueError("Destination directory must be owned by the current user")


def _new_private_file(destination: Path) -> None:
    if not destination.is_absolute():
        raise ValueError("Destination must be an absolute path")
    _private_directory(destination.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(destination, flags, 0o600)
    os.close(fd)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_verified(source: Path, destination: Path) -> dict:
    """Use a consistent SQLite online backup, never copy a live DB byte-for-byte."""
    inspect_store(source)
    source = source.expanduser()
    destination = destination.expanduser()
    if not source.is_absolute() or not destination.is_absolute():
        raise ValueError("Source and destination paths must be absolute")
    if source.resolve() == destination.resolve():
        raise ValueError("Refusing to overwrite the source")
    _new_private_file(destination)
    try:
        # source is opened read-only; backup() obtains a consistent snapshot
        # even if other connections are writing to the original database.
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5) as src:
            with sqlite3.connect(destination, timeout=5) as dst:
                src.backup(dst)
        inspected = inspect_store(destination)
        return {
            "result": "PASS", "sha256": _digest(destination),
            "sqlite_quick_check": inspected["sqlite_quick_check"],
            "file_mode": inspected["file_mode"], "destination_created": True,
            "contains_sensitive_review_records": True,
            "restore_onto_live_store": False,
        }
    except Exception:
        # A failed NEW destination does not remain as a misleading backup.
        destination.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--restore-test", required=True, type=Path,
                        help="NEW disposable restore destination, never live approval store")
    options = parser.parse_args(argv)
    try:
        src, backup, restored = (
            path.expanduser() for path in
            (options.source, options.backup, options.restore_test))
        if len({str(p.resolve()) for p in (src, backup, restored)}) != 3:
            raise ValueError("Source, backup and restore destinations must differ")
        if backup.exists() or backup.is_symlink() or restored.exists() or restored.is_symlink():
            raise ValueError("Backup and restore destination must not exist")
        original_info = inspect_store(src)
        original = copy_verified(src, backup)
        rehearsal = copy_verified(backup, restored)
        if original["sha256"] != rehearsal["sha256"]:
            raise ValueError("Disposable restore SHA-256 does not match backup snapshot")
        result = {
            "result": "PASS", "source_preflight": original_info["result"],
            "backup_preflight": "PASS", "restore_rehearsal": "PASS",
            "backup_and_restore_sha256_equal": True,
            "sha256": original["sha256"],
            "review_rows_exported_to_stdout": False,
            "production_store_modified": False,
            "backup_and_restore_files_are_sensitive": True,
        }
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"result": "FAIL", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
