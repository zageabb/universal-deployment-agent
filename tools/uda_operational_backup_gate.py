"""Selected backup gate for the controller, not a live execution entry point.

A caller must supply an independently verified writer guard and application
storage protection. No default approval or writer bypass is provided.
"""
from pathlib import Path
from tools.uda_selected_backup_assets import selection
from tools.uda_quiesced_backup import create
from tools.uda_backup_inventory import capture
from tools.uda_production_release_plan import digest
from tools.uda_maintenance_evidence import approval, backup_evidence, timestamp
from tools.uda_production_integrity_gates import units_idle
from tools.v2_systemd_restore_rehearsal import UNIT_FILES, OVERRIDES, ENABLED


def required_assets():
    return {"systemd-user/" + n for n in (*UNIT_FILES, *OVERRIDES, *ENABLED)} | {
        "bin/uda-trigger-ci", "runtime/sci-next-current", "config/config.json",
        "state/identity.db", "runtime/deploy_agent.py", "runtime/dashboard.py"}


def prepare(session, adapter, original, home, destination, approval_record,
            writer_guard, application_guard):
    record = session.load()
    if record["phase"] != "isolated":
        raise ValueError("Isolated transaction required")
    plan = record["plan"]
    approval(plan, approval_record)
    roots, selected, excluded = selection(home)
    def guard():
        return writer_guard() is True and application_guard(plan, excluded) is True
    if not guard():
        raise ValueError("Writer or application protection missing")
    units_idle(adapter, original)
    inventory = capture(roots, selected=selected, excluded=excluded)
    if not required_assets() <= set(inventory):
        raise ValueError("Required backup assets missing")
    report = create(session, adapter, original, roots, destination, approval_record,
                    guard, selected=selected, excluded=excluded)
    record = session.load()
    if record["backup_inventory_receipt"]["inventory_sha256"] != digest(inventory):
        raise ValueError("Backup selection drift")
    record["selected_backup_scope"] = {
        "inventory_sha256": digest(inventory),
        "excluded": list(excluded),
        "required_assets": sorted(required_assets()),
        "contract_sha256": plan["sha256"],
    }
    session.save(record)
    return report


def verify_before_apply(session, adapter, original, home, writer_guard, application_guard):
    record = session.load()
    if record["phase"] != "isolated":
        raise ValueError("Isolated transaction required")
    plan = record["plan"]
    scope = record["selected_backup_scope"]
    roots, selected, excluded = selection(home)
    if scope["contract_sha256"] != plan["sha256"] or scope["excluded"] != list(excluded):
        raise ValueError("Backup scope binding mismatch")
    if writer_guard() is not True or application_guard(plan, excluded) is not True:
        raise ValueError("Writer or application protection missing")
    units_idle(adapter, original)
    inventory = capture(roots, selected=selected, excluded=excluded)
    if not required_assets() <= set(inventory) or scope["required_assets"] != sorted(required_assets()):
        raise ValueError("Required backup assets missing")
    if digest(inventory) != scope["inventory_sha256"] or digest(inventory) != record["backup_inventory_receipt"]["inventory_sha256"]:
        raise ValueError("Backup source inventory drift")
    evidence = record["backup_evidence"]
    verified = backup_evidence(plan, evidence, isolated_at=timestamp(evidence["started_at"]))
    if verified != record["backup_archive_receipt"]:
        raise ValueError("Backup receipt drift")
    units_idle(adapter, original)
    if writer_guard() is not True or application_guard(plan, excluded) is not True:
        raise ValueError("Writer or application protection lost")
    return True
