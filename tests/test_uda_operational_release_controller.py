import pytest
from contextlib import contextmanager
from tools import uda_operational_release_controller as c


class Session:
    def __init__(self):
        self.record = {}
    def begin(self, plan):
        self.record = {"phase": "prepared", "plan": plan}
    def load(self):
        return dict(self.record)
    def save(self, record):
        self.record = record
    def advance(self, phase):
        self.record["phase"] = phase


@pytest.fixture
def lab(tmp_path, monkeypatch):
    events = []
    held = [False]
    s = Session()
    plan = {"contract": {"venv": {"receipt": {}}}}
    def event(name, locked=None):
        def fn(*args, **kwargs):
            if locked is not None:
                assert held[0] is locked
            events.append(name)
            return True
        return fn
    @contextmanager
    def lock(*args, **kwargs):
        assert kwargs["exclusive"] and not held[0]
        held[0] = True
        events.append("lock")
        try:
            yield
        finally:
            held[0] = False
            events.append("unlock")
    @contextmanager
    def legacy(*args):
        assert held[0]
        events.append("legacy_enter")
        try:
            yield event("legacy_check", True)
        finally:
            events.append("legacy_exit")
    monkeypatch.setattr(c, "hold", legacy)
    monkeypatch.setattr(c, "maintenance_lock", lock)
    monkeypatch.setattr(c, "load_config", lambda *a: {})
    monkeypatch.setattr(c, "approval", event("approval", False))
    monkeypatch.setattr(c, "inspect", lambda *a, **k: plan)
    monkeypatch.setattr(c, "verify_unchanged", event("plan", False))
    monkeypatch.setattr(c, "original", lambda *a: {})
    monkeypatch.setattr(c.permission, "bind", event("bind", False))
    monkeypatch.setattr(c.permission, "authorize", event("authorize"))
    monkeypatch.setattr(c.integrity, "preserved", event("preserved"))
    monkeypatch.setattr(c.integrity, "units_idle", event("idle", True))
    monkeypatch.setattr(c.integrity, "environment", lambda *a: {"fixture": True})
    monkeypatch.setattr(c.integrity, "verify_environment", event("environment", True))
    def isolate(*a):
        events.append("isolate")
        s.advance("isolated")
    monkeypatch.setattr(c.services, "isolate", isolate)
    monkeypatch.setattr(c, "reisolate", event("reisolate", False))
    monkeypatch.setattr(c.application, "create", event("application", True))
    monkeypatch.setattr(c.backup, "prepare", event("backup", True))
    monkeypatch.setattr(c.backup, "verify_before_apply", event("verify_backup", True))
    monkeypatch.setattr(c.payload, "apply", event("apply", True))
    monkeypatch.setattr(c.payload, "switch", event("switch", True))
    monkeypatch.setattr(c.payload, "restore_environment", event("restore_environment", True))
    monkeypatch.setattr(c.payload, "restore_files", event("restore_files", True))
    def restore(adapter, states, probe):
        assert not held[0]
        events.append("restore")
        if not probe("home"):
            raise RuntimeError("probe failed")
    monkeypatch.setattr(c.services, "restore", restore)
    controller = c.Controller(s, tmp_path, tmp_path, None,
                              lambda: True, lambda: True,
                              lambda _: True, lambda _: True, process_review=lambda _: True)
    return controller, plan, events, s


def execute(lab):
    controller, plan, _, _ = lab
    return controller.execute(plan, {}, None, None)


def test_success_order(lab):
    _, _, events, s = lab
    assert execute(lab) == "accepted"
    assert s.record["phase"] == "accepted"
    expected = ["bind", "isolate", "lock", "application", "backup", "verify_backup",
                "apply", "switch", "unlock", "restore"]
    assert [e for e in events if e in expected] == expected
    assert events.index("lock") < events.index("legacy_enter") < events.index("apply") < events.index("legacy_exit") < events.index("unlock")


def test_backup_failure_recovers(lab, monkeypatch):
    _, _, events, s = lab
    def fail(*a, **k):
        raise ValueError("backup failure")
    monkeypatch.setattr(c.backup, "verify_before_apply", fail)
    assert execute(lab) == "rolled_back"
    assert "apply" not in events
    assert "restore_files" in events
    assert s.record["phase"] == "rolled_back"


def test_candidate_health_failure_recovers(lab):
    controller, _, events, s = lab
    controller.probe_candidate = lambda _: False
    assert execute(lab) == "rolled_back"
    assert events.count("lock") == 2
    assert events.count("unlock") == 2
    assert events.count("legacy_enter") == events.count("legacy_exit") == 2
    assert "reisolate" in events
    assert s.record["phase"] == "rolled_back"


def test_missing_writer_stops_mutation(lab):
    controller, _, events, s = lab
    controller.writer_guard = lambda: False
    with pytest.raises(ValueError, match="writer exclusion"):
        execute(lab)
    assert "apply" not in events
    assert not s.record
    assert "isolate" not in events
