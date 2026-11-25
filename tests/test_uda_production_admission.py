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
