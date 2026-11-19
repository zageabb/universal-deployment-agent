"""V2 multi-service durable, tamper-evident journal and review-only recovery scan.

The journal stores operation names/state only, not service commands, environment
values or snapshots. Every record is fsynced; records form a SHA-256 hash chain.
No automatic recovery or systemd process control exists in this module.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import uuid
import fcntl

from onboarding import OnboardingError

MAX_SIZE = 5 * 1024 * 1024
MAX_RECORD = 16 * 1024
ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
LABEL = re.compile(
    r"^(?:lock_acquired|snapshot:[a-z0-9-]+|preflight_complete|"
    r"intent:(?:stop|restore):[a-z0-9-]+|"
    r"configured:[a-z0-9-]+|started:[a-z0-9-]+|"
    r"healthy:[a-z0-9-]+|degraded:[a-z0-9-]+|"
    r"rollback_started|compensated:(?:stop|restore):[a-z0-9-]+|"
    r"rollback_complete|complete)$"
)
UNDO = re.compile(r"^(?:stop|restore):[a-z0-9-]+$")
STATES = {"preparing", "applying", "healthy", "degraded", "rolling_back",
          "rolled_back", "rollback_failed"}


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _private_directory(root: Path) -> Path:
    if not isinstance(root, Path) or root.is_symlink():
        raise OnboardingError("Journal directory must be a private real directory")
    if not root.exists():
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise OnboardingError("Journal directory has unsafe permissions")
    return root


def _id(value: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise OnboardingError("Invalid V2 transaction ID")
    return value


def _check_record(record: dict) -> dict:
    if not isinstance(record, dict) or record.get("state") not in STATES:
        raise OnboardingError("Invalid V2 journal state")
    events = record.get("events", [])
    pending = record.get("pending_undo", [])
    if not isinstance(events, list) or not events or not isinstance(pending, list):
        raise OnboardingError("Invalid V2 journal sequence")
    if len(events) > 150 or len(pending) > 80:
        raise OnboardingError("Oversized V2 journal sequence")
    if not all(isinstance(x, str) and LABEL.fullmatch(x) for x in events):
        raise OnboardingError("Journal operation name must be allowlisted")
    if not all(isinstance(x, str) and UNDO.fullmatch(x) for x in pending):
        raise OnboardingError("Invalid journal compensation intent")
    # Copy ONLY allowlisted keys, preserving no arbitrary source fields.
    return {
        "state": record["state"],
        "event": events[-1],
        "pending_undo": pending[:],
    }


def _read_chain(raw: bytes, transaction_id: str) -> list[dict]:
    if len(raw) > MAX_SIZE:
        raise OnboardingError("Journal exceeded size limit")
    if raw and not raw.endswith(b"\n"):
        raise OnboardingError("Journal has incomplete trailing record")
    previous = "0" * 64
    items = []
    for line in raw.splitlines():
        if len(line) > MAX_RECORD:
            raise OnboardingError("Oversized journal event")
        try:
            item = json.loads(line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OnboardingError("Corrupted journal JSON") from exc
        if (not isinstance(item, dict) or set(item) !=
                {"transaction_id", "index", "previous", "payload", "digest"}):
            raise OnboardingError("Unexpected journal record shape")
        payload = item["payload"]
        normalized = _check_record({
            "state": payload.get("state") if isinstance(payload, dict) else None,
            "events": [payload.get("event")] if isinstance(payload, dict) else None,
            "pending_undo": payload.get("pending_undo") if isinstance(payload, dict) else None,
        })
        if payload != normalized:
            raise OnboardingError("Invalid journal event payload")
        signed = {key: item[key] for key in ("transaction_id", "index", "previous", "payload")}
        if (item["transaction_id"] != transaction_id or
                type(item["index"]) is not int or item["index"] != len(items) or
                item["previous"] != previous):
            raise OnboardingError("Journal identity or ordering mismatch")
        digest = hashlib.sha256(_canonical(signed)).hexdigest()
        if digest != item["digest"]:
            raise OnboardingError("Journal digest mismatch")
        previous = digest
        items.append(item)
    return items


class DurableServiceJournal:
    """Only trusted local workers can use this; never accepts manifest commands."""

    def __init__(self, directory: Path, transaction_id: str):
        self.directory = _private_directory(directory)
        self.transaction_id = _id(transaction_id)
        self.path = self.directory / (transaction_id + ".jsonl")

    def __call__(self, record: dict) -> None:
        payload = _check_record(record)
        if self.path.is_symlink():
            raise OnboardingError("Journal path cannot be a symlink")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            if os.fstat(fd).st_mode & 0o077:
                raise OnboardingError("Journal file permissions too broad")
            with os.fdopen(os.dup(fd), "rb") as handle:
                raw = handle.read(MAX_SIZE + 1)
            chain = _read_chain(raw, self.transaction_id)
            if chain and chain[-1]["payload"]["state"] in ("healthy", "degraded", "rolled_back", "rollback_failed"):
                raise OnboardingError("Terminal journal cannot be extended")
            previous = chain[-1]["digest"] if chain else "0" * 64
            signed = {"transaction_id": self.transaction_id, "index": len(chain),
                      "previous": previous, "payload": payload}
            entry = {**signed, "digest": hashlib.sha256(_canonical(signed)).hexdigest()}
            line = _canonical(entry) + b"\n"
            if len(line) > MAX_RECORD or len(raw) + len(line) > MAX_SIZE:
                raise OnboardingError("Journal full")
            os.lseek(fd, 0, os.SEEK_END)
            if os.write(fd, line) != len(line):
                raise OnboardingError("Journal short write")
            os.fsync(fd)
            if not chain:
                parent_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
        finally:
            os.close(fd)

    def records(self) -> list[dict]:
        if self.path.is_symlink():
            raise OnboardingError("Journal path cannot be a symlink")
        if not self.path.exists():
            return []
        if self.path.stat().st_mode & 0o077:
            raise OnboardingError("Journal file permissions too broad")
        return _read_chain(self.path.read_bytes(), self.transaction_id)

    def recovery_status(self) -> dict:
        """Read-only status; never invokes rollback, restart or service updates."""
        chain = self.records()
        if not chain:
            return {"transaction_id": self.transaction_id, "status": "not_started",
                    "pending_undo": [], "manual_approval_required": False,
                    "can_auto_replay": False}
        last = chain[-1]["payload"]
        return {"transaction_id": self.transaction_id,
                "status": last["state"],
                "pending_undo": last["pending_undo"][:],
                "manual_approval_required": last["state"] not in ("healthy", "degraded", "rolled_back"),
                "can_auto_replay": False,
                "records": len(chain)}
