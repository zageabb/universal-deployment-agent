from copy import deepcopy
import pytest
from tools import uda_production_release_plan as p
from tools import uda_production_admission as a
from tools.uda_controlled_activation import State, UNITS, WEB, TIMERS


def fixture():
    old = {"status": "present", "mode": 420, "sha256": "old"}
    new = {"mode": 420, "sha256": "new", "size": 3}
    entries = {n: {"action": "replace", "installed": old, "candidate": new}
               for n in a.REPLACEMENTS}
    for i in range(35):
        entries[f"runtime/new{i}.py"] = {"action": "add", "installed": {"status": "missing"}, "candidate": new}
    for i in range(14):
        entries[f"runtime/keep{i}.py"] = {"action": "unchanged", "installed": old, "candidate": new}
    for i in range(7):
        entries[f"units/keep{i}"] = {"action": "preserve_review", "installed": old, "candidate": {"mode": 420, "sha256": "old"}}
    states = {u: vars(State("active", "enabled", sub="waiting" if u in TIMERS else "running")
               if u in WEB + TIMERS else State("inactive", "static", sub="dead")) for u in UNITS}
    return {"actions": a.EXPECTED, "payload_count": 62, "entries": entries, "units": {}, "issues": []}, {"status": "BASELINE_PASS", "actions": a.EXPECTED, "unit_states": states}


def plan():
    return p.contract(*fixture(), "revision", "host", 1000)


def test_contract():
    value = plan()
    assert len(value["contract"]["mutations"]) == 41
    assert len(value["contract"]["preserved"]) == 21
    assert not value["production_upgrade_authorized"]
    p.verify_unchanged(value, deepcopy(value))


def test_tampered_digest():
    value = plan()
    changed = deepcopy(value)
    changed["contract"]["host"] = "different"
    with pytest.raises(ValueError, match="digest"):
        p.verify_unchanged(value, changed)


def test_valid_but_changed_contract():
    value = plan()
    changed = p.contract(*fixture(), "other revision", "host", 1000)
    with pytest.raises(ValueError, match="drift"):
        p.verify_unchanged(value, changed)


def test_isolation():
    value = plan()
    isolated = {u: State("inactive", s["enabled"], sub="dead") for u, s in value["contract"]["original_states"].items()}
    assert p.isolation_review(value, isolated, writers_quiescent=True, backup_verified=True)["status"] == "ISOLATION_REVIEW_PASS"
    with pytest.raises(ValueError, match="evidence missing"):
        p.isolation_review(value, isolated, writers_quiescent=True, backup_verified=False)


def test_running_units_refused():
    value = plan()
    running = {u: State(**s) for u, s in value["contract"]["original_states"].items()}
    with pytest.raises(ValueError, match="isolation incomplete"):
        p.isolation_review(value, running, writers_quiescent=True, backup_verified=True)
