from datetime import datetime, timezone, timedelta
import os
import socket
import pytest
from tools import uda_application_backup_creation as c
from tools.uda_maintenance_protection import bind
from tools.uda_production_release_plan import digest


class Session:
    def __init__(self, record):
        self.record = record
    def load(self):
        import copy
        return copy.deepcopy(self.record)
    def save(self, record):
        self.record = record


@pytest.fixture
def lab(tmp_path, monkeypatch):
    home = tmp_path / "home"
    runtime = home / ".local/share/deployment-agent"
    active = runtime / "sci-next-releases/release"
    active.mkdir(parents=True)
    (active / "app.py").write_text("fixture")
    (runtime / "sci-next-current").symlink_to(active)
    backup = tmp_path / "backup"
    backup.mkdir(mode=0o700)
    now = datetime.now(timezone.utc)
    body = {"host": socket.gethostname(), "uid": os.getuid(), "revision": "fixture"}
    plan = {"contract": body, "sha256": digest(body), "status": "PLAN_ONLY",
            "production_upgrade_authorized": False}
    evidence = {"version": 1, "decision": "APPROVE_UDA_V2_INSTALL",
                "contract_sha256": plan["sha256"], **body, "operator": "fixture",
                "not_before": (now - timedelta(minutes=1)).isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat()}
    s = Session({"phase": "prepared", "plan": plan})
    bind(s, evidence)
    s.record["phase"] = "isolated"
    monkeypatch.setattr(c, "units_idle", lambda *a: True)
    return s, home, active, backup / "release.tar"


def create(lab, guard=lambda: True):
    s, home, _, destination = lab
    return c.create(s, None, None, home, destination, guard)


def test_create_and_verify(lab):
    s, home, _, destination = lab
    report = create(lab)
    assert report["status"] == "RELEASE_TREE_BACKUP_VERIFIED"
    assert destination.stat().st_mode & 0o777 == 0o600
    assert c.verify_bound(s, home, s.record["plan"], ["runtime/sci-next-releases"])


def test_missing_writer_guard(lab):
    s, _, _, destination = lab
    with pytest.raises(ValueError, match="Writer protection missing"):
        create(lab, lambda: False)
    assert not destination.exists()
    assert "application_backup" not in s.record


def test_existing_archive_preserved(lab):
    s, _, _, destination = lab
    destination.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        create(lab)
    assert destination.read_bytes() == b"existing"
    assert "application_backup" not in s.record


def test_repeat_refused(lab):
    create(lab)
    with pytest.raises(ValueError, match="Fresh isolated"):
        create(lab)


def test_source_drift_after_backup(lab):
    s, home, active, _ = lab
    create(lab)
    (active / "app.py").write_text("changed")
    with pytest.raises(ValueError, match="inventory drift"):
        c.verify_bound(s, home, s.record["plan"], ["runtime/sci-next-releases"])


def test_wrong_exclusion_refused(lab):
    s, home, _, _ = lab
    create(lab)
    with pytest.raises(ValueError, match="scope mismatch"):
        c.verify_bound(s, home, s.record["plan"], [])


def test_nonisolated_refused(lab):
    s, _, _, destination = lab
    s.record["phase"] = "prepared"
    with pytest.raises(ValueError, match="Fresh isolated"):
        create(lab)
    assert not destination.exists()
