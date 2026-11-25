from dataclasses import replace
import pytest
from tools import uda_production_service_isolation as s
from tools.uda_controlled_activation import State, TIMERS, WORKERS, WEB, UNITS
from tools import uda_release_transaction_journal as j
from tools.uda_production_release_plan import digest


def baseline():
    return {u: State("active", "enabled", sub="waiting" if u in TIMERS else "running")
            if u in TIMERS + WEB else State("inactive", "static", sub="dead") for u in UNITS}


class Adapter:
    def __init__(self):
        self.states = baseline()
        self.events = []
        self.fail = None

    def snapshot(self):
        return dict(self.states)

    def change(self, action, unit):
        assert unit in TIMERS + WEB
        self.events.append((action, unit))
        if self.fail == (action, unit):
            raise RuntimeError("fixture failure")
        self.states[unit] = replace(self.states[unit], active="active" if action == "start" else "inactive",
                                   sub=("waiting" if unit in TIMERS else "running") if action == "start" else "dead")


def begin(session):
    body = {"venv": {"receipt": {"fixture": True}}, "original_states": {u: vars(v) for u,v in baseline().items()}}
    session.begin({"contract": body, "sha256": digest(body), "status": "PLAN_ONLY", "production_upgrade_authorized": False})


def test_isolate_and_restore(tmp_path):
    tmp_path.chmod(0o700)
    adapter = Adapter()
    with j.locked(tmp_path) as session:
        begin(session)
        states = s.isolate(adapter, session)
        assert session.load()["phase"] == "isolated"
        assert all(v.active == "inactive" for v in states.values())
    assert adapter.events == [("stop", u) for u in TIMERS + tuple(reversed(WEB))]
    def probe(target):
        adapter.events.append(("health", target))
        return True
    assert s.restore(adapter, baseline(), probe) == baseline()
    assert adapter.events[-7:] == [("start", u) for u in WEB] + [("health", "home"), ("health", "dashboard")] + [("start", u) for u in TIMERS]


def test_worker_drains_without_stop():
    adapter = Adapter()
    for u in TIMERS:
        adapter.change("stop", u)
    worker = WORKERS[0]
    adapter.states[worker] = replace(adapter.states[worker], active="activating", sub="start")
    def sleep(_):
        adapter.states[worker] = baseline()[worker]
    s.drain(adapter, baseline(), sleep=sleep)
    assert all(u not in WORKERS for _,u in adapter.events)


def test_drain_timeout():
    adapter = Adapter()
    for u in TIMERS:
        adapter.change("stop", u)
    adapter.states[WORKERS[0]] = replace(adapter.states[WORKERS[0]], active="activating", sub="start")
    times = iter([0, 2])
    with pytest.raises(TimeoutError, match="no worker killed"):
        s.drain(adapter, baseline(), timeout=1, clock=lambda: next(times))
    assert all(u not in WORKERS for _,u in adapter.events)


def test_baseline_drift(tmp_path):
    tmp_path.chmod(0o700)
    adapter = Adapter()
    adapter.states[WEB[0]] = replace(adapter.states[WEB[0]], enabled="disabled")
    with j.locked(tmp_path) as session:
        begin(session)
        with pytest.raises(ValueError, match="drift"):
            s.isolate(adapter, session)
        assert session.load()["phase"] == "prepared"
    assert not adapter.events


def test_partial_stop_failure_is_journalled(tmp_path):
    tmp_path.chmod(0o700)
    adapter = Adapter()
    adapter.fail = ("stop", TIMERS[1])
    with j.locked(tmp_path) as session:
        begin(session)
        with pytest.raises(RuntimeError):
            s.isolate(adapter, session)
        assert session.load()["phase"] == "isolating"


def test_failed_health_keeps_timers_stopped():
    adapter = Adapter()
    with pytest.raises(RuntimeError, match="Health"):
        s.restore(adapter, baseline(), lambda target: target == "home")
    assert all(adapter.states[u].active == "inactive" for u in TIMERS)


def test_failed_timer_start_stops_started_timers():
    adapter = Adapter()
    adapter.fail = ("start", TIMERS[1])
    with pytest.raises(RuntimeError):
        s.restore(adapter, baseline(), lambda _: True)
    assert all(adapter.states[u].active == "inactive" for u in TIMERS)


def test_allowlist(monkeypatch):
    monkeypatch.setattr(s.subprocess, "run", lambda *a, **k: pytest.fail("Unexpected subprocess"))
    adapter = s.UserSystemd()
    for action, unit in [("disable", TIMERS[0]), ("stop", WORKERS[0]), ("stop", "caddy.service"), ("start", "unrelated.timer")]:
        with pytest.raises(ValueError, match="not allowed"):
            adapter.change(action, unit)


def test_timer_isolation_lost():
    adapter = Adapter()
    with pytest.raises(ValueError, match="Timer isolation lost"):
        s.drain(adapter, baseline())


def test_enablement_drift_refused():
    adapter = Adapter()
    adapter.states[WEB[0]] = replace(adapter.states[WEB[0]], enabled="disabled")
    with pytest.raises(ValueError, match="Unexpected unit state"):
        s.restore(adapter, baseline(), lambda _: True)
    assert not adapter.events
