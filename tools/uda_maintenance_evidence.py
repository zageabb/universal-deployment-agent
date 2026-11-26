"""Local maintenance evidence validation; not an authorization issuer.

A trusted operator must create the approval independently of the installer.
The approval is bound to one release contract, host, UID and bounded window.
This is a local same-UID trust model, not a cryptographic signature.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
import socket
import stat
from pathlib import Path

from tools.uda_production_release_plan import digest
from tools.uda_release_transaction_journal import private


def read_private_json(path):
    private(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        s = os.fstat(stream.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_nlink != 1 or stat.S_IMODE(s.st_mode) != 0o600 or s.st_size > 1024 * 1024:
            raise ValueError("Unsafe maintenance evidence file")
        return json.load(stream)


def timestamp(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("Timezone required")
    return dt.astimezone(timezone.utc)


def approval(plan, evidence, *, now=None):
    body = plan["contract"]
    if plan.get("status") != "PLAN_ONLY" or plan.get("production_upgrade_authorized") is not False or digest(body) != plan["sha256"]:
        raise ValueError("Invalid release contract")
    if body["host"] != socket.gethostname() or body["uid"] != os.getuid():
        raise ValueError("Contract host or UID mismatch")
    if evidence.get("version") != 1 or evidence.get("decision") != "APPROVE_UDA_V2_INSTALL":
        raise ValueError("Explicit maintenance approval required")
    for key, value in {"contract_sha256": plan["sha256"], "host": body["host"], "uid": body["uid"], "revision": body["revision"]}.items():
        if evidence.get(key) != value:
            raise ValueError("Approval binding mismatch: " + key)
    start, end = timestamp(evidence["not_before"]), timestamp(evidence["expires_at"])
    now = datetime.now(timezone.utc) if now is None else now
    if not start <= now < end or end - start > timedelta(hours=4):
        raise ValueError("Maintenance approval outside valid window")
    if not isinstance(evidence.get("operator"), str) or not evidence["operator"].strip():
        raise ValueError("Operator identity required")
    return {"approval_sha256": digest(evidence), "contract_sha256": plan["sha256"],
            "expires_at": end.isoformat(), "operator": evidence["operator"]}


def backup_evidence(plan, evidence, *, isolated_at, now=None):
    """Validate evidence metadata and archive bytes, not archive completeness.

    An independent backup/restore procedure must establish consistency and
    coverage before this evidence can be used as an operational gate.
    """
    if evidence.get("version") != 1 or evidence.get("contract_sha256") != plan["sha256"]:
        raise ValueError("Backup contract mismatch")
    now = datetime.now(timezone.utc) if now is None else now
    started = timestamp(evidence["started_at"])
    completed = timestamp(evidence["completed_at"])
    if not isolated_at <= started <= completed <= now:
        raise ValueError("Backup not created after isolation")
    if now - completed > timedelta(hours=1):
        raise ValueError("Backup evidence stale")
    path = Path(evidence["archive"])
    if not path.is_absolute():
        raise ValueError("Absolute backup path required")
    private(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600 or before.st_size == 0:
            raise ValueError("Unsafe backup archive")
        h = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Backup changed during verification")
    if evidence.get("archive_sha256") != h.hexdigest() or evidence.get("size") != before.st_size:
        raise ValueError("Backup archive integrity mismatch")
    return {"archive_sha256": h.hexdigest(), "size": before.st_size,
            "evidence_sha256": digest(evidence), "archive_bytes_verified": True,
            "backup_completeness_verified": False, "production_upgrade_authorized": False}
