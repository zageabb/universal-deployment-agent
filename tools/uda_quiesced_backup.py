"""Backup creation primitive for an isolated transaction; no live CLI.

Caller must establish authorization and provide a trustworthy writer guard.
The guard is checked repeatedly, not a substitute for enforced exclusion.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import tarfile
from tools.uda_backup_inventory import capture, verify_snapshot, hash_stream, write_selected
from tools.uda_maintenance_evidence import backup_evidence, approval
from tools.uda_release_transaction_journal import private
from tools.uda_install_journal import sync_dir
from tools.uda_production_integrity_gates import units_idle


def create(session, adapter, original, roots, destination, approval_record, writer_guard, *, selected=None, excluded=()):
    record = session.load()
    if record["phase"] != "isolated":
        raise ValueError("Isolated transaction required")
    plan = record["plan"]
    approval(plan, approval_record)
    private(destination.parent)
    if not destination.is_absolute():
        raise ValueError("Absolute backup destination required")
    for root in roots.values():
        if destination.resolve().is_relative_to(root.resolve()):
            raise ValueError("Backup destination inside source")
    def guard():
        units_idle(adapter, original)
        if writer_guard() is not True:
            raise ValueError("Writer exclusion not established")
    guard()
    isolated_at = datetime.now(timezone.utc)
    before = capture(roots, selected=selected, excluded=excluded)
    databases = sorted(n for n,e in before.items()
                       if e["type"] == "file" and n.lower().endswith((".db", ".sqlite", ".sqlite3")))
    guard()
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        with tarfile.open(fileobj=stream, mode="w", dereference=False) as tar:
            write_selected(tar, roots, before)
        stream.flush()
        os.fsync(stream.fileno())
    sync_dir(destination.parent)
    guard()
    report = verify_snapshot(destination, roots, before, databases, selected=selected, excluded=excluded)
    with destination.open("rb") as stream:
        sha = hash_stream(stream)
    completed = datetime.now(timezone.utc)
    evidence = {"version": 1, "contract_sha256": plan["sha256"],
                "archive": str(destination), "archive_sha256": sha,
                "size": destination.stat().st_size,
                "started_at": isolated_at.isoformat(), "completed_at": completed.isoformat()}
    verified = backup_evidence(plan, evidence, isolated_at=isolated_at)
    guard()
    approval(plan, approval_record)
    record = session.load()
    if record["phase"] != "isolated" or record["plan"] != plan:
        raise ValueError("Transaction changed")
    record["backup_evidence"] = evidence
    record["backup_inventory_receipt"] = report
    record["backup_archive_receipt"] = verified
    session.save(record)
    return {"status": "SELECTED_ROOT_BACKUP_PASS", "entries": report["entries"],
            "sqlite_checked": report["sqlite_checked"], "archive_sha256": sha,
            "production_root_coverage_verified": False,
            "production_upgrade_authorized": False}
