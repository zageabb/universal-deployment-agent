"""V2-003 transaction-bound recovery evidence and READ-ONLY interruption plan.

No replay, service start/stop, database write or deployment permission exists
here. A pre-mutation snapshot is stored in a private directory and its exact
transaction, bundle SHA, service order and byte digests are checked against a
hash-chained journal before displaying compensation intent.

A local SHA-256 hash detects damage, but is not an external signature. The
privileged worker must separately authenticate an operator and verify trusted
release/ownership evidence before recovery can ever execute.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from onboarding import OnboardingError
from onboarding_v2_recovery_journal import DurableServiceJournal, _id
from onboarding_v2_approval import _digest_bundle

MAX_EVIDENCE = 3 * 1024 * 1024
MAX_SERVICES = 20
HEX = re.compile(r"^[0-9a-f]{64}$")
SERVICE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _private(root: Path) -> Path:
    if not isinstance(root, Path) or not root.is_absolute() or root.is_symlink():
        raise OnboardingError("Snapshot storage requires private absolute directory")
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise OnboardingError("Snapshot storage directory is not private")
    return root


def _payload(transaction_id: str, bundle: dict, snapshots: dict) -> dict:
    _id(transaction_id)
    app, source, bundle_hash = _digest_bundle(bundle)
    ordered = bundle["order"]
    if not isinstance(snapshots, dict) or not 1 <= len(snapshots) <= MAX_SERVICES:
        raise OnboardingError("Snapshot inventory missing or oversized")
    if set(snapshots) != set(ordered) or len(ordered) != len(set(ordered)):
        raise OnboardingError("Snapshot units do not match reviewed bundle")
    units = {}
    for unit in ordered:
        record = snapshots[unit]
        if (not isinstance(record, dict) or set(record) != {"bytes", "running"} or
                type(record["running"]) is not bool or
                (record["bytes"] is not None and
                 (not isinstance(record["bytes"], bytes) or len(record["bytes"]) > 65536))):
            raise OnboardingError("Invalid pre-mutation service snapshot")
        content = record["bytes"]
        units[unit] = {
            "bytes": None if content is None else base64.b64encode(content).decode("ascii"),
            "sha256": None if content is None else hashlib.sha256(content).hexdigest(),
            "running": record["running"],
        }
    return {"version": 1, "transaction_id": transaction_id,
            "application": app, "source_commit": source, "bundle_sha256": bundle_hash,
            "unit_order": ordered[:], "units": units}


def save_recovery_evidence(root: Path, transaction_id: str, bundle: dict,
                           snapshots: dict) -> Path:
    """Create once, durably, BEFORE any mutation. Never overwrite snapshot."""
    directory = _private(root)
    data = _payload(transaction_id, bundle, snapshots)
    checksum = hashlib.sha256(_json(data)).hexdigest()
    content = _json({**data, "integrity_sha256": checksum}) + b"\n"
    if len(content) > MAX_EVIDENCE:
        raise OnboardingError("Recovery evidence too large")
    path = directory / (transaction_id + ".json")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise OnboardingError("Recovery transaction evidence already exists") from exc
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        fd_dir = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd_dir)
        finally:
            os.close(fd_dir)
    except Exception:
        # Existing evidence is left for manual investigation; never overwrite.
        raise
    return path


def _load(root: Path, transaction_id: str) -> dict:
    path = _private(root) / (_id(transaction_id) + ".json")
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise OnboardingError("Recovery evidence missing, linked or exposed")
    if path.stat().st_size > MAX_EVIDENCE:
        raise OnboardingError("Recovery evidence exceeds size limit")
    try:
        data = json.loads(path.read_bytes())
    except (OSError, ValueError, UnicodeError) as exc:
        raise OnboardingError("Recovery evidence is unreadable") from exc
    keys = {"version", "transaction_id", "application", "source_commit",
            "bundle_sha256", "unit_order", "units", "integrity_sha256"}
    if not isinstance(data, dict) or set(data) != keys or data["version"] != 1:
        raise OnboardingError("Unknown recovery evidence layout")
    checksum = data.pop("integrity_sha256")
    if not isinstance(checksum, str) or not HEX.fullmatch(checksum) or (
            hashlib.sha256(_json(data)).hexdigest() != checksum):
        raise OnboardingError("Recovery snapshot integrity mismatch")
    data["integrity_sha256"] = checksum
    return data


def plan_interrupted_recovery(*, snapshot_root: Path, journal_root: Path,
                              transaction_id: str, reviewed_bundle: dict) -> dict:
    """Produce no-execution compensation checklist from strictly verified evidence."""
    app, commit, digest = _digest_bundle(reviewed_bundle)
    source = _load(snapshot_root, transaction_id)
    if (source["transaction_id"] != transaction_id or
            source["application"] != app or
            source["source_commit"] != commit or
            source["bundle_sha256"] != digest or
            source["unit_order"] != reviewed_bundle["order"] or
            set(source["units"]) != set(reviewed_bundle["units"])):
        raise OnboardingError("Recovery evidence is not for the reviewed transaction")
    for unit, value in source["units"].items():
        if not isinstance(value, dict) or set(value) != {"bytes", "sha256", "running"}:
            raise OnboardingError("Malformed recovery service snapshot")
        if type(value["running"]) is not bool:
            raise OnboardingError("Invalid previous service state")
        blob = value["bytes"]
        try:
            original = None if blob is None else base64.b64decode(blob, validate=True)
        except (ValueError, TypeError) as exc:
            raise OnboardingError("Invalid recovery snapshot bytes") from exc
        if (original is not None and len(original) > 65536) or (
                (original is None) != (value["sha256"] is None)):
            raise OnboardingError("Invalid recovery snapshot content")
        if original is not None and hashlib.sha256(original).hexdigest() != value["sha256"]:
            raise OnboardingError("Recovery snapshot byte digest mismatch")
    journal = DurableServiceJournal(journal_root, transaction_id)
    records = journal.records()  # Validates every hash chain entry, not just tail.
    if not records:
        raise OnboardingError("No durable transaction intents found")
    last = records[-1]["payload"]
    if last["state"] in ("healthy", "degraded", "rolled_back"):
        return {"transaction_id": transaction_id, "state": "terminal",
                "pending_compensations": [], "requires_operator_review": False,
                "can_execute": False, "automatic_replay_allowed": False}
    intended = [e["payload"]["event"][7:] for e in records
                if e["payload"]["event"].startswith("intent:")]
    pending = last["pending_undo"]
    if (not isinstance(pending, list) or len(pending) != len(set(pending)) or
            any(op not in intended for op in pending)):
        raise OnboardingError("Pending compensation does not match journal intents")
    for op in pending:
        action, sep, name = op.partition(":")
        if sep != ":" or action not in ("stop", "restore") or name not in source["units"]:
            # Existing journal uses service names; a separate trusted mapping
            # must bind each service to exactly one systemd unit.
            raise OnboardingError("Recovery operation not in reviewed unit allowlist")
    # The journal records SERVICE NAMES, whereas the bundle contains UNIT
    # names. There is no trustworthy mapping without a separate signed plan.
    # Never guess a mapping or permit automatic replay.
    return {"transaction_id": transaction_id, "state": "review_required",
            "application": app, "source_commit": commit, "bundle_sha256": digest,
            "pending_compensations": list(reversed(pending)),
            "prior_unit_states": {unit: value["running"] for unit, value in source["units"].items()},
            "requires_operator_review": True, "can_execute": False,
            "automatic_replay_allowed": False,
            "blocking_reason": "Signed service-to-unit mapping and independent recovery approval required"}
