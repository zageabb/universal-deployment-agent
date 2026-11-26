"""Disposable integrated controller tests using the actual payload primitives."""
import os
import signal
import pytest
from test_uda_production_payload_transaction import fixture, assert_old
from test_uda_production_service_isolation import Adapter, baseline
from tools import uda_integrated_release_controller as c
from tools import uda_release_transaction_journal as j
from tools.uda_production_release_plan import digest
from tools.uda_controlled_activation import TIMERS, WEB


class Gates:
    def __init__(self, plan):
        self.plan = plan
        self.approved = True
        self.backup = True
        self.candidate_health = True
        self.restored_health = True

    def authorized(self, plan):
        return self.approved

    def current_plan(self):
        return self.plan

    def verify_preserved(self, plan):
        return True

    def quiescent(self):
        return True

    def fresh_backup(self, plan):
        return self.backup

    def verify_original_environment(self, runtime):
        return (runtime / "venv/marker").read_bytes() == b"old"

    def probe_candidate(self, target):
        return self.candidate_health

    def probe_restored(self, target):
        return self.restored_health

    def reisolate(self, adapter, original):
        for u in TIMERS + WEB:
            adapter.change("stop", u)
        return True


def setup(tmp_path, monkeypatch):
    runtime, stage, journal, plan = fixture(tmp_path, monkeypatch)
    plan["contract"]["original_states"] = {u: vars(v) for u,v in baseline().items()}
    plan["sha256"] = digest(plan["contract"])
    return runtime, stage, journal, plan, Adapter(), Gates(plan)


def test_success(tmp_path, monkeypatch):
    runtime, stage, journal, plan, adapter, gates = setup(tmp_path, monkeypatch)
    with j.locked(journal) as session:
        assert c.execute(session, stage, runtime, adapter, gates, plan) == "accepted"
        assert session.load()["phase"] == "accepted"
    assert (runtime / "venv").is_symlink()
    assert adapter.states == baseline()


@pytest.mark.parametrize("failure", ["backup", "candidate_health"])
def test_rollback(tmp_path, monkeypatch, failure):
    runtime, stage, journal, plan, adapter, gates = setup(tmp_path, monkeypatch)
    setattr(gates, failure, False)
    with j.locked(journal) as session:
        assert c.execute(session, stage, runtime, adapter, gates, plan) == "rolled_back"
        assert session.load()["phase"] == "rolled_back"
    assert_old(runtime, plan)
    assert adapter.states == baseline()


def test_authorization_refusal(tmp_path, monkeypatch):
    runtime, stage, journal, plan, adapter, gates = setup(tmp_path, monkeypatch)
    gates.approved = False
    with j.locked(journal) as session:
        with pytest.raises(ValueError, match="authorization"):
            c.execute(session, stage, runtime, adapter, gates, plan)
        assert not session.path.exists()
    assert not adapter.events


def test_failed_recovery_health(tmp_path, monkeypatch):
    runtime, stage, journal, plan, adapter, gates = setup(tmp_path, monkeypatch)
    gates.candidate_health = gates.restored_health = False
    with j.locked(journal) as session:
        with pytest.raises(RuntimeError, match="Health"):
            c.execute(session, stage, runtime, adapter, gates, plan)
        assert session.load()["phase"] == "review"
    assert_old(runtime, plan)
    assert all(adapter.states[u].active == "inactive" for u in TIMERS)


@pytest.mark.parametrize("boundary", ["after:runtime/dashboard.py", "after_rename", "after_link"])
def test_real_sigkill(tmp_path, monkeypatch, boundary):
    runtime, stage, journal, plan, adapter, gates = setup(tmp_path, monkeypatch)
    apply, switch = c.payload.apply, c.payload.switch
    def interrupt(point):
        if point == boundary:
            os.kill(os.getpid(), signal.SIGKILL)
    monkeypatch.setattr(c.payload, "apply", lambda *args: apply(*args, interrupt=interrupt))
    monkeypatch.setattr(c.payload, "switch", lambda *args: switch(*args, interrupt=interrupt))
    pid = os.fork()
    if pid == 0:
        try:
            with j.locked(journal) as session:
                c.execute(session, stage, runtime, adapter, gates, plan)
        finally:
            os._exit(1)
    _, status = os.waitpid(pid, 0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    with j.locked(journal) as session:
        c.recover(session, stage, runtime, adapter, gates)
        assert session.load()["phase"] == "rolled_back"
    assert_old(runtime, plan)
