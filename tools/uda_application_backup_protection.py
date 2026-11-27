"""Separate SCI Next release-code protection; not application data consistency.

Read-only verification of an independently created archive. A stable inventory
does not prove writer exclusion or coverage of external application databases.
"""
from pathlib import Path
from tools.uda_backup_inventory import capture, verify_snapshot
from tools.uda_maintenance_protection import application_pointer, verify_application_pointer
from tools.uda_maintenance_evidence import backup_evidence, timestamp
from tools.uda_production_release_plan import digest


def verify(home, plan, evidence, *, now=None):
    pointer = application_pointer(home)
    if evidence["pointer"] != pointer:
        raise ValueError("Application pointer evidence drift")
    roots = {"sci-next-releases": home / ".local/share/deployment-agent/sci-next-releases"}
    archive = Path(evidence["archive"])
    if archive.resolve().is_relative_to((home / ".local/share/deployment-agent").resolve()):
        raise ValueError("Application backup inside runtime")
    receipt = backup_evidence(plan, evidence, isolated_at=timestamp(evidence["started_at"]), now=now)
    inventory = capture(roots)
    if digest(inventory) != evidence["inventory_sha256"]:
        raise ValueError("Application release inventory drift")
    databases = [n for n, e in inventory.items() if e["type"] == "file"
                 and n.lower().endswith((".db", ".sqlite", ".sqlite3"))]
    checked = verify_snapshot(archive, roots, inventory, databases)
    if backup_evidence(plan, evidence, isolated_at=timestamp(evidence["started_at"]), now=now) != receipt:
        raise ValueError("Application archive receipt drift")
    verify_application_pointer(home, pointer)
    return {"status": "RELEASE_TREE_BACKUP_VERIFIED",
            "contract_sha256": plan["sha256"],
            "pointer": pointer, "inventory_sha256": checked["inventory_sha256"],
            "archive_sha256": receipt["archive_sha256"], "entries": checked["entries"],
            "external_application_data_verified": False,
            "writer_exclusion_verified": False, "production_upgrade_authorized": False}
