from types import SimpleNamespace
import pytest
from tools import uda_production_admission as a
from tools.uda_controlled_activation import State, UNITS, TIMERS, WEB, WORKERS


def test_private_group():
    owner = SimpleNamespace(pw_uid=1000, pw_gid=1000, pw_name="owner")
    other = SimpleNamespace(pw_uid=1001, pw_gid=1001, pw_name="other")
    group = SimpleNamespace(gr_mem=[])
    assert a.private_group(1000, 1000, [owner, other], group)
    other.pw_gid = 1000
    assert not a.private_group(1000, 1000, [owner, other], group)
    other.pw_gid = 1001
    group.gr_mem = ["other"]
    assert not a.private_group(1000, 1000, [owner, other], group)


def baseline():
    return {u: State("active", "enabled", sub="waiting" if u in TIMERS else "running")
            if u in WEB + TIMERS else State("inactive", "static", sub="dead") for u in UNITS}


def test_running_topology():
    a.review_states(baseline())


def test_worker_running_refused():
    states = baseline()
    states[WORKERS[0]] = State("active", "static", sub="running")
    with pytest.raises(ValueError, match="Worker active"):
        a.review_states(states)


def test_timer_disabled_refused():
    states = baseline()
    states[TIMERS[0]] = State("active", "disabled", sub="waiting")
    with pytest.raises(ValueError, match="topology changed"):
        a.review_states(states)


def report():
    entries = {n: {"action": "replace"} for n in a.REPLACEMENTS}
    entries["bin/uda-trigger-ci"] = {"action": "preserve_review",
        "installed": {"status": "present", "mode": 493, "sha256": "same"},
        "candidate": {"mode": 493, "sha256": "same"}}
    return {"actions": dict(a.EXPECTED), "payload_count": 62, "entries": entries,
            "issues": ["runtime: group-writable root requires review"]}


def test_scope():
    a.review_inventory(report())


def test_changed_scope():
    r = report()
    r["actions"]["add"] = 36
    with pytest.raises(ValueError, match="scope changed"):
        a.review_inventory(r)


def test_preserved_mismatch():
    r = report()
    r["entries"]["bin/uda-trigger-ci"]["candidate"]["sha256"] = "changed"
    with pytest.raises(ValueError, match="Preserved payload differs"):
        a.review_inventory(r)


def test_unresolved_issue():
    r = report()
    r["issues"].append("unsafe root")
    with pytest.raises(ValueError, match="Unresolved"):
        a.review_inventory(r)


def test_timer_transient_retried(monkeypatch):
    busy = baseline()
    busy[TIMERS[0]] = State("active", "enabled", sub="running")
    snapshots = iter([busy, baseline()])
    monkeypatch.setattr(a, "read_states", lambda: next(snapshots))
    monkeypatch.setattr(a.time, "sleep", lambda _: None)
    assert a.stable_states() == baseline()


def test_persistent_timer_transient_refused(monkeypatch):
    busy = baseline()
    busy[TIMERS[0]] = State("active", "enabled", sub="running")
    monkeypatch.setattr(a, "read_states", lambda: busy)
    monkeypatch.setattr(a.time, "sleep", lambda _: None)
    with pytest.raises(ValueError, match="snapshot 2/2"):
        a.stable_states(attempts=2)


def test_failed_unit_not_retried(monkeypatch):
    failed = baseline()
    failed[WORKERS[0]] = State("failed", "static", sub="failed", result="exit-code")
    monkeypatch.setattr(a, "read_states", lambda: failed)
    monkeypatch.setattr(a.time, "sleep", lambda _: pytest.fail("Hard failure retried"))
    with pytest.raises(ValueError, match="snapshot 1/6"):
        a.stable_states()


def test_explicit_systemctl_properties(monkeypatch):
    def run(args, **kwargs):
        assert args[:3] == ["systemctl", "--user", "show"]
        assert args[4:] == ["-p", "ActiveState", "-p", "SubState",
                           "-p", "UnitFileState", "-p", "LoadState", "-p", "Result"]
        state = baseline()[args[3]]
        return SimpleNamespace(stdout=f"ActiveState={state.active}\nSubState={state.sub}\nUnitFileState={state.enabled}\nLoadState=loaded\nResult=success\n")
    monkeypatch.setattr(a.subprocess, "run", run)
    assert a.read_states() == baseline()
