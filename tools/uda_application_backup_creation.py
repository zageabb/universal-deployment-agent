"""Create a separate release-code archive under an isolated transaction.

No service control, external database backup or production CLI. The caller
must maintain independent writer protection throughout this operation.
"""
from datetime import datetime, timezone
import os
import tarfile
from tools.uda_backup_inventory import capture, write_selected, hash_stream
from tools.uda_application_backup_protection import verify
from tools.uda_maintenance_protection import application_pointer, authorize
from tools.uda_production_release_plan import digest
from tools.uda_release_transaction_journal import private
from tools.uda_install_journal import sync_dir
from tools.uda_production_integrity_gates import units_idle


def create(session, adapter, original, home, destination, writer_guard):
    record = session.load()
    if record["phase"] != "isolated" or "application_backup" in record:
        raise ValueError("Fresh isolated application backup required")
    plan = record["plan"]
    authorize(session)
    if not destination.is_absolute():
        raise ValueError("Absolute backup destination required")
    private(destination.parent)
    runtime = home / ".local/share/deployment-agent"
    for root in (runtime, home / ".config/deployment-agent",
                 home / ".local/state/deployment-agent"):
        if destination.resolve().is_relative_to(root.resolve()):
            raise ValueError("Application backup inside protected storage")
    def guard():
        units_idle(adapter, original)
        if writer_guard() is not True:
            raise ValueError("Writer protection missing")
        authorize(session)
    guard()
    started = datetime.now(timezone.utc)
    pointer = application_pointer(home)
    roots = {"sci-next-releases": runtime / "sci-next-releases"}
    inventory = capture(roots)
    guard()
    fd = os.open(destination, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w+b") as stream:
        with tarfile.open(fileobj=stream, mode="w", dereference=False) as tar:
            write_selected(tar, roots, inventory)
        stream.flush()
        os.fsync(stream.fileno())
        size = os.fstat(stream.fileno()).st_size
        stream.seek(0)
        sha = hash_stream(stream)
    sync_dir(destination.parent)
    guard()
    evidence = {"version": 1, "contract_sha256": plan["sha256"],
                "archive": str(destination), "size": size, "archive_sha256": sha,
                "started_at": started.isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "pointer": pointer, "inventory_sha256": digest(inventory)}
    receipt = verify(home, plan, evidence)
    guard()
    current = session.load()
    if current != record:
        raise ValueError("Transaction changed during application backup")
    current["application_backup"] = {"evidence": evidence, "receipt": receipt}
    session.save(current)
    return receipt


def verify_bound(session, home, plan, excluded):
    record = session.load()
    if record["plan"] != plan or list(excluded) != ["runtime/sci-next-releases"]:
        raise ValueError("Application backup scope mismatch")
    bound = record["application_backup"]
    if verify(home, plan, bound["evidence"]) != bound["receipt"]:
        raise ValueError("Application backup receipt mismatch")
    return True
