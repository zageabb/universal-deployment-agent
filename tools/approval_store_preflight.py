#!/usr/bin/env python3
"""Read-only, non-sensitive health check for an existing UDA approval SQLite store.

Never creates the database, runs schema changes, fetches request rows or
connects to a deployment service. Uses SQLite URI mode=ro (read-only).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys


def inspect_store(path: Path) -> dict:
    """Fail closed on missing/insecure files; return metadata, not review rows."""
    path = path.expanduser()
    if not path.is_absolute():
        raise ValueError("Approval store path must be absolute")
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Approval store path/parent must not be symbolic links")
    parent = path.parent
    if not parent.is_dir():
        raise ValueError("Approval store parent does not exist")
    meta = path.stat()
    if not stat.S_ISREG(meta.st_mode):
        raise ValueError("Approval store must be a regular file")
    if meta.st_mode & 0o077:
        raise ValueError("Approval store must not be group/world accessible")
    if meta.st_uid != os.getuid():
        raise ValueError("Approval store must be owned by the executing account")
    if not os.access(path, os.R_OK):
        raise ValueError("Approval store cannot be read")
    # Use SQLite's URI mode=ro. Never create a missing DB or execute writes.
    uri = path.as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=3) as conn:
            dbs = conn.execute("PRAGMA database_list").fetchall()
            if len(dbs) != 1 or dbs[0][1] != "main":
                raise ValueError("Unexpected attached database")
            names = {
                name for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('requests','audit')")
            }
            triggers = {
                name for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' "
                    "AND name IN ('audit_no_update','audit_no_delete')")
            }
            check = conn.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise ValueError("Approval store could not be checked safely") from exc
    if names != {"requests", "audit"}:
        raise ValueError("Required approval tables are missing")
    if triggers != {"audit_no_update", "audit_no_delete"}:
        raise ValueError("Audit protection triggers are missing")
    if check is None or check[0] != "ok":
        raise ValueError("SQLite quick_check did not pass")
    return {
        "result": "PASS",
        "sqlite_quick_check": "ok",
        "tables_present": sorted(names),
        "audit_triggers_present": sorted(triggers),
        "file_mode": oct(stat.S_IMODE(meta.st_mode)),
        "owner_matches_process": True,
        "read_only_check": True,
        "requests_or_audit_contents_exported": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True,
                        help="Absolute path to an EXISTING approval SQLite file")
    args = parser.parse_args(argv)
    try:
        result = inspect_store(args.store)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"result": "FAIL", "error": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
