"""Durable installation journal prototype, restricted to synthetic temp labs.

No production path or live activation API. POSIX local-filesystem semantics.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import tempfile
import uuid


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save(root: Path, record: dict) -> None:
    durable_write(root / "journal.json", json.dumps(record, sort_keys=True).encode())


def load(root: Path) -> dict:
    return json.loads((root / "journal.json").read_text())


NAMES = ("existing.py", "new.py")
OLD = b"synthetic old runtime"
NEW = b"synthetic candidate runtime"


def validate_lab(root: Path) -> None:
    # Only the CLI creates labs; all names are fixed synthetic fixture names.
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Invalid lab")
    if root.stat().st_uid != os.getuid() or stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise ValueError("Lab must be owner-private")
    if not root.name.startswith("uda-journal-lab-"):
        raise ValueError("Synthetic lab required")
    for name in ("runtime", "backup"):
        p = root / name
        if p.is_symlink() or not p.is_dir():
            raise ValueError("Unsafe lab directory")
    for p in (root / "journal.json", root / "lock",
              *(root / "runtime" / n for n in NAMES),
              *(root / "backup" / n for n in NAMES)):
        if p.is_symlink() or (p.exists() and not p.is_file()):
            raise ValueError("Unsafe lab file")


def init_lab(root: Path) -> None:
    (root / "runtime").mkdir(mode=0o700)
    (root / "backup").mkdir(mode=0o700)
    sync_dir(root)
    durable_write(root / "runtime/existing.py", OLD, 0o640)
    durable_write(root / "runtime/unmanaged", b"preserve")


def locked(root: Path):
    validate_lab(root)
    fd = os.open(root / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    stream = os.fdopen(fd, "r+b")
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        stream.close()
        raise
    return stream


def install(root: Path, crash: str = "") -> None:
    with locked(root):
        if (root / "journal.json").exists():
            raise ValueError("Existing transaction must be reviewed")
        record = {"version": 1, "id": str(uuid.uuid4()), "phase": "prepared", "entries": {}}
        for name in NAMES:
            path = root / "runtime" / name
            if path.exists():
                old = path.read_bytes()
                mode = stat.S_IMODE(path.stat().st_mode)
                durable_write(root / "backup" / name, old)
                if checksum((root / "backup" / name).read_bytes()) != checksum(old):
                    raise ValueError("Backup verification failed")
                record["entries"][name] = {"old": checksum(old), "mode": mode, "state": "pending"}
            else:
                record["entries"][name] = {"old": None, "mode": None, "state": "pending"}
        save(root, record)
        for name in NAMES:
            entry = record["entries"][name]
            entry["state"] = "intent"
            record["phase"] = "applying"
            save(root, record)
            if crash == "before:" + name:
                os.kill(os.getpid(), signal.SIGKILL)
            durable_write(root / "runtime" / name, NEW, 0o644)
            if crash == "after:" + name:
                os.kill(os.getpid(), signal.SIGKILL)
            entry["state"] = "applied"
            save(root, record)
        record["phase"] = "complete"
        save(root, record)


def review(root: Path) -> dict:
    with locked(root):
        record = load(root)
        return {"transaction_id": record["id"], "phase": record["phase"],
                "recovery_required": record["phase"] in {"prepared", "applying", "recovering"},
                "production_upgrade_authorized": False}


def recover(root: Path, crash: str = "") -> None:
    with locked(root):
        record = load(root)
        if record["phase"] not in {"prepared", "applying", "recovering"}:
            raise ValueError("Transaction is not interrupted")
        entries = record["entries"]
        if set(entries) != set(NAMES) or record["version"] != 1:
            raise ValueError("Unknown journal")
        # Validate all backups and current bytes before any recovery mutation.
        for name, entry in entries.items():
            if entry["state"] not in {"pending", "intent", "applied", "restored"}:
                raise ValueError("Unknown entry state")
            if entry["old"] is not None:
                backup = root / "backup" / name
                if entry["mode"] != 0o640 or checksum(backup.read_bytes()) != entry["old"]:
                    raise ValueError("Backup integrity failure")
            dest = root / "runtime" / name
            actual = checksum(dest.read_bytes()) if dest.exists() else None
            allowed = {entry["old"]}
            if entry["state"] in {"intent", "applied"}:
                allowed.add(checksum(NEW))
            if actual not in allowed:
                raise ValueError("Unexpected runtime bytes; recovery refused")
        record["phase"] = "recovering"
        save(root, record)
        for name in reversed(NAMES):
            entry = entries[name]
            dest = root / "runtime" / name
            if entry["old"] is None:
                dest.unlink(missing_ok=True)
                sync_dir(dest.parent)
            else:
                durable_write(dest, (root / "backup" / name).read_bytes(), entry["mode"])
            if crash == "restore:" + name:
                os.kill(os.getpid(), signal.SIGKILL)
            entry["state"] = "restored"
            save(root, record)
        for name, entry in entries.items():
            dest = root / "runtime" / name
            if entry["old"] is None:
                if dest.exists():
                    raise ValueError("New file still present")
            elif checksum(dest.read_bytes()) != entry["old"] or stat.S_IMODE(dest.stat().st_mode) != entry["mode"]:
                raise ValueError("Restoration verification failed")
        record["phase"] = "rolled_back"
        save(root, record)


def main() -> int:
    # No operator-supplied target; child processes only use synthetic labs
    # created by the independent test harness.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "recover"])
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--crash", default="")
    args = parser.parse_args()
    (install if args.action == "install" else recover)(args.lab, args.crash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
