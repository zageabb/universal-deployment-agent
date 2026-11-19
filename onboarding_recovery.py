"""Crash-recovery snapshots and explicitly approved compensation replay.

No automatic service operations occur on import or discovery. Snapshot files
contain sensitive registry content and must remain outside Git, owned by UDA's
dedicated worker account, mode 0600 in a 0700 directory.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import secrets
import uuid

from onboarding import OnboardingError

FIELDS = ("registry", "unit", "proxy", "attestation")
TERMINAL = {"completed", "rolled_back"}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
STEPS = {"service", "start", "registry", "proxy", "attestation"}
MAX_SNAPSHOT = 2 * 1024 * 1024


def _id(value: str) -> str:
    if not isinstance(value, str) or not UUID_RE.fullmatch(value):
        raise OnboardingError("Invalid recovery transaction ID")
    return value


def _private_root(root: Path) -> Path:
    root = root.expanduser()
    if root.is_symlink():
        raise OnboardingError("Recovery root must not be a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise OnboardingError("Recovery root must be a private directory")
    return root


def save_snapshot(root: Path, transaction_id: str, snapshot: dict) -> Path:
    """Persist recovery bytes BEFORE any mutation; never overwrite an existing ID."""
    identifier = _id(transaction_id)
    if not isinstance(snapshot, dict) or snapshot.get("transaction_id") != identifier:
        raise OnboardingError("Recovery snapshot transaction mismatch")
    if set(snapshot) != set(FIELDS) | {"transaction_id"}:
        raise OnboardingError("Unexpected recovery snapshot fields")
    packed = {"transaction_id": identifier}
    for key in FIELDS:
        value = snapshot[key]
        if value is not None and not isinstance(value, bytes):
            raise OnboardingError("Recovery snapshot must contain bytes or null")
        packed[key] = None if value is None else base64.b64encode(value).decode("ascii")
    data = (json.dumps(packed, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(data) > MAX_SNAPSHOT:
        raise OnboardingError("Recovery snapshot exceeds size limit")
    directory = _private_root(root)
    target = directory / (identifier + ".json")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(target, flags, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        # Durable directory entry required to survive sudden power loss.
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        # Do not silently replace a previously committed recovery snapshot.
        raise
    return target


def load_snapshot(root: Path, transaction_id: str) -> dict:
    identifier = _id(transaction_id)
    directory = _private_root(root)
    path = directory / (identifier + ".json")
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise OnboardingError("Recovery snapshot missing, linked, or exposed")
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_SNAPSHOT:
            raise ValueError("oversized")
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != set(FIELDS) | {"transaction_id"}:
            raise ValueError("invalid shape")
        if value["transaction_id"] != identifier:
            raise ValueError("identity mismatch")
        snapshot = {"transaction_id": identifier}
        for key in FIELDS:
            blob = value[key]
            snapshot[key] = None if blob is None else base64.b64decode(blob, validate=True)
        return snapshot
    except (ValueError, OSError, TypeError) as exc:
        raise OnboardingError("Recovery snapshot failed integrity/shape checks") from exc


def inspect_incomplete(journal_root: Path) -> list[dict]:
    """Read-only inventory of unfinished transactions; never replay by itself."""
    directory = _private_root(journal_root)
    pending = []
    for file in directory.glob("*.jsonl"):
        if file.is_symlink() or not UUID_RE.fullmatch(file.stem):
            continue
        if file.stat().st_mode & 0o077:
            raise OnboardingError("Recovery journal permissions are too broad")
        try:
            with file.open(encoding="utf-8") as handle:
                events = [json.loads(line) for line in handle if line.strip()]
        except (OSError, ValueError) as exc:
            raise OnboardingError("Recovery journal is unreadable") from exc
        if not events:
            continue
        event = events[-1]
        if event.get("transaction_id") != file.stem:
            raise OnboardingError("Journal identity mismatch")
        if event.get("state") not in TERMINAL:
            pending.append({
                "transaction_id": file.stem,
                "state": event.get("state", "unknown"),
                "pending_undo": event.get("pending_undo", []),
                "requires_manual_approval": True,
            })
    return pending


def replay_compensations(snapshot: dict, journal_state: dict, plan: dict, adapter, *,
                         explicitly_approved: bool = False) -> dict:
    """Manual recovery only. Caller must acquire host-wide deployment lock."""
    if not explicitly_approved:
        raise OnboardingError("Crash recovery requires explicit administrator approval")
    txn_id = _id(snapshot.get("transaction_id"))
    if journal_state.get("transaction_id") != txn_id:
        raise OnboardingError("Recovery journal and snapshot mismatch")
    if journal_state.get("state") in TERMINAL:
        raise OnboardingError("Transaction is already terminal")
    remaining = journal_state.get("pending_undo")
    if not isinstance(remaining, list) or any(x not in STEPS for x in remaining):
        raise OnboardingError("Recovery journal has no valid pending operations")
    if not remaining:
        raise OnboardingError("No compensation intent recorded; manual investigation required")
    # Replay reverse compensations. Adapter must verify every path is scoped
    # to the recorded transaction and must make all operations idempotent.
    succeeded = []
    failures = []
    adapter.acquire_lock()
    try:
        for step in reversed(remaining):
            try:
                adapter.compensate(step, snapshot, plan)
                succeeded.append(step)
            except Exception:
                failures.append(step)
        return {"transaction_id": txn_id,
                "state": "rollback_failed" if failures else "rolled_back",
                "reverted": succeeded,
                "failed": failures,
                "requires_manual_approval": bool(failures)}
    finally:
        adapter.release_lock()
