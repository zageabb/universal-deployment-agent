"""Operational protection evidence; not an OS-wide writer exclusion mechanism.

Only independently established protection can satisfy the injected guard.
No production process is stopped by this module.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import socket
from tools.uda_maintenance_evidence import approval, timestamp
from tools.uda_production_release_plan import digest

RECOVERY_PHASES = {"isolating", "isolated", "applying", "switching", "health", "recovering", "review"}


def bind(session, evidence, *, now=None):
    record = session.load()
    if record["phase"] != "prepared" or "maintenance_approval" in record:
        raise ValueError("Fresh prepared transaction required")
    now = datetime.now(timezone.utc) if now is None else now
    receipt = approval(record["plan"], evidence, now=now)
    record["maintenance_approval"] = {"evidence": evidence, "receipt": receipt,
                                      "validated_at": now.isoformat()}
    session.save(record)
    return receipt


def authorize(session, *, recovery=False, now=None):
    record = session.load()
    plan = record["plan"]
    bound = record["maintenance_approval"]
    evidence = bound["evidence"]
    validated = timestamp(bound["validated_at"])
    now = datetime.now(timezone.utc) if now is None else now
    if validated > now:
        raise ValueError("Approval validation timestamp in future")
    if approval(plan, evidence, now=validated) != bound["receipt"]:
        raise ValueError("Persisted approval receipt mismatch")
    if recovery:
        if record["phase"] not in RECOVERY_PHASES:
            raise ValueError("Rollback-only authorization unavailable")
    else:
        approval(plan, evidence, now=now)
    return True


def application_pointer(home):
    runtime = home / ".local/share/deployment-agent"
    releases = runtime / "sci-next-releases"
    pointer = runtime / "sci-next-current"
    if releases.is_symlink() or not releases.is_dir() or not pointer.is_symlink():
        raise ValueError("Invalid SCI Next storage boundary")
    target = pointer.resolve(strict=True)
    if target.parent != releases.resolve() or not target.is_dir():
        raise ValueError("Invalid SCI Next release target")
    def identity(path):
        s = path.lstat()
        return [s.st_dev, s.st_ino, s.st_uid, s.st_mode]
    return {"pointer": str(pointer.readlink()), "pointer_identity": identity(pointer),
            "releases_identity": identity(releases), "target_identity": identity(target)}


def verify_application_pointer(home, expected):
    if application_pointer(home) != expected:
        raise ValueError("SCI Next release boundary drift")
    return True


def protection(session, home, expected_pointer, writer_guard, application_backup_guard):
    """Fail closed; pointer stability alone is not application backup evidence."""
    if writer_guard() is not True:
        raise ValueError("Independent writer exclusion missing")
    verify_application_pointer(home, expected_pointer)
    if application_backup_guard(session.load()["plan"], expected_pointer) is not True:
        raise ValueError("Independent application backup protection missing")
    return True
