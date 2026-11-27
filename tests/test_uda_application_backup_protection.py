from datetime import datetime, timezone
import tarfile
import hashlib
import pytest
from tools import uda_application_backup_protection as p
from tools.uda_backup_inventory import capture, write_selected
from tools.uda_maintenance_protection import application_pointer
from tools.uda_production_release_plan import digest


@pytest.fixture
def lab(tmp_path):
    home = tmp_path / "home"
    runtime = home / ".local/share/deployment-agent"
    releases = runtime / "sci-next-releases"
    active = releases / "release"
    active.mkdir(parents=True)
    (active / "app.py").write_text("fixture")
    (runtime / "sci-next-current").symlink_to(active)
    backup = tmp_path / "backup"
    backup.mkdir(mode=0o700)
    archive = backup / "release.tar"
    roots = {"sci-next-releases": releases}
    inventory = capture(roots)
    with tarfile.open(archive, "w", dereference=False) as tar:
        write_selected(tar, roots, inventory)
    archive.chmod(0o600)
    now = datetime.now(timezone.utc)
    plan = {"sha256": "fixture-contract"}
    evidence = {"version": 1, "contract_sha256": plan["sha256"],
                "archive": str(archive), "size": archive.stat().st_size,
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "started_at": now.isoformat(), "completed_at": now.isoformat(),
                "pointer": application_pointer(home), "inventory_sha256": digest(inventory)}
    return home, active, plan, evidence, now


def test_verified_release_tree(lab):
    home, _, plan, evidence, now = lab
    result = p.verify(home, plan, evidence, now=now)
    assert result["status"] == "RELEASE_TREE_BACKUP_VERIFIED"
    assert result["external_application_data_verified"] is False
    assert result["writer_exclusion_verified"] is False


def test_changed_release(lab):
    home, active, plan, evidence, now = lab
    (active / "app.py").write_text("changed")
    with pytest.raises(ValueError, match="inventory drift"):
        p.verify(home, plan, evidence, now=now)


def test_changed_pointer(lab):
    home, active, plan, evidence, now = lab
    other = active.parent / "other"
    other.mkdir()
    pointer = active.parent.parent / "sci-next-current"
    pointer.unlink()
    pointer.symlink_to(other)
    with pytest.raises(ValueError, match="pointer evidence drift"):
        p.verify(home, plan, evidence, now=now)


def test_changed_archive(lab):
    home, _, plan, evidence, now = lab
    from pathlib import Path
    with Path(evidence["archive"]).open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="archive integrity mismatch"):
        p.verify(home, plan, evidence, now=now)


def test_wrong_contract(lab):
    home, _, plan, evidence, now = lab
    with pytest.raises(ValueError, match="contract mismatch"):
        p.verify(home, {"sha256": "different"}, evidence, now=now)
