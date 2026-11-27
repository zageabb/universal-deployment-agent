import pytest
from tools import uda_operational_backup_gate as g
from tools.uda_production_release_plan import digest


class Session:
    def __init__(self):
        self.record = {"phase": "isolated", "plan": {"sha256": "fixture"}}
    def load(self):
        return self.record
    def save(self, record):
        self.record = record


@pytest.fixture
def lab(tmp_path, monkeypatch):
    session = Session()
    inventory = {name: {"type": "file"} for name in g.required_assets()}
    excluded = ("runtime/sci-next-releases",)
    monkeypatch.setattr(g, "selection", lambda _: ({}, {}, excluded))
    monkeypatch.setattr(g, "capture", lambda *a, **k: inventory)
    monkeypatch.setattr(g, "approval", lambda *a: True)
    monkeypatch.setattr(g, "units_idle", lambda *a: True)
    def create(*a, **k):
        session.record.update(backup_inventory_receipt={"inventory_sha256": digest(inventory)},
                              backup_evidence={"started_at": "2026-11-27T12:00:00+00:00"},
                              backup_archive_receipt={"verified": True})
        return {"status": "SELECTED_ROOT_BACKUP_PASS"}
    monkeypatch.setattr(g, "create", create)
    monkeypatch.setattr(g, "backup_evidence", lambda *a, **k: {"verified": True})
    return session, inventory, tmp_path


def prepare(lab, writer=lambda: True, app=lambda *a: True):
    s, _, home = lab
    return g.prepare(s, None, None, home, home / "backup.tar", {}, writer, app)


def verify(lab, writer=lambda: True, app=lambda *a: True):
    s, _, home = lab
    return g.verify_before_apply(s, None, None, home, writer, app)


def test_prepare_verify(lab):
    assert prepare(lab)["status"] == "SELECTED_ROOT_BACKUP_PASS"
    assert verify(lab) is True


@pytest.mark.parametrize("writer,app", [(False, True), (True, False)])
def test_missing_guard(lab, writer, app):
    with pytest.raises(ValueError, match="protection missing"):
        prepare(lab, lambda: writer, lambda *a: app)
    assert "selected_backup_scope" not in lab[0].record


def test_source_drift(lab):
    prepare(lab)
    lab[1]["runtime/dashboard.py"]["sha256"] = "changed"
    with pytest.raises(ValueError, match="inventory drift"):
        verify(lab)


def test_missing_required_asset(lab):
    del lab[1]["config/config.json"]
    with pytest.raises(ValueError, match="assets missing"):
        prepare(lab)


def test_lost_guard(lab):
    prepare(lab)
    with pytest.raises(ValueError, match="protection missing"):
        verify(lab, writer=lambda: False)


def test_receipt_drift(lab):
    prepare(lab)
    lab[0].record["backup_archive_receipt"] = {"verified": False}
    with pytest.raises(ValueError, match="receipt drift"):
        verify(lab)
