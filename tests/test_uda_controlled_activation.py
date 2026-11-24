import pytest
from tools import uda_controlled_activation as a


@pytest.fixture
def states():
    original = {u: a.State("inactive", "static", sub="dead") for u in a.WORKERS}
    original.update({u: a.State("active", "enabled", sub="running") for u in a.WEB})
    original.update({u: a.State("active", "enabled", sub="waiting") for u in a.TIMERS})
    original[a.TIMERS[1]] = a.State("inactive", "enabled", sub="dead")
    original[a.TIMERS[2]] = a.State("active", "disabled", sub="waiting")
    isolated = {u: a.State("inactive", s.enabled, sub="dead") for u, s in original.items()}
    return original, isolated


def test_success_preserves_mixed_timer_states(states):
    result = a.rehearse(*states)
    assert result["outcome"] == "activated"
    assert result["original_states_restored"]
    assert result["caddy_unchanged"] and result["unrelated_unchanged"]
    assert not result["systemctl_invoked"]
    assert not result["production_upgrade_authorized"]
    assert ("start", a.TIMERS[1]) not in result["events"]
    assert result["events"].index(("health", "dashboard")) < result["events"].index(("start", a.TIMERS[0]))


@pytest.mark.parametrize("options", [{"writers_quiescent": False}, {"backup_verified": False}])
def test_missing_evidence(states, options):
    with pytest.raises(ValueError, match="evidence"):
        a.rehearse(*states, **options)


def test_running_worker_refused(states):
    original, isolated = states
    isolated[a.WORKERS[0]] = a.State("active", "static", sub="running")
    with pytest.raises(ValueError, match="isolation"):
        a.rehearse(original, isolated)


def test_missing_unit_refused(states):
    del states[1][a.WORKERS[2]]
    with pytest.raises(ValueError, match="inventory"):
        a.rehearse(*states)


def test_transitional_state_refused(states):
    states[1][a.TIMERS[0]] = a.State("activating", "enabled", sub="waiting")
    with pytest.raises(ValueError, match="Unstable"):
        a.rehearse(*states)


def test_enablement_drift_refused(states):
    states[1][a.TIMERS[0]] = a.State("inactive", "disabled", sub="dead")
    with pytest.raises(ValueError, match="Enablement"):
        a.rehearse(*states)


@pytest.mark.parametrize("target", ["home", "dashboard"])
def test_failed_health_rolls_back(states, target):
    result = a.rehearse(*states, health={target: False})
    assert result["outcome"] == "rolled_back"
    assert result["original_states_restored"]
    assert result["events"].index(("rollback", "payload")) < result["events"].index(("start", a.TIMERS[0]))


def test_failed_timer_start_rolls_back(states):
    result = a.rehearse(*states, fail_start=a.TIMERS[2])
    assert result["outcome"] == "rolled_back"
    assert result["events"].index(("stop", a.TIMERS[0])) < result["events"].index(("rollback", "payload"))


@pytest.mark.parametrize("options,match", [
    ({"rollback_verified": False}, "Rollback not verified"),
    ({"restored_health": False}, "Restored runtime health"),
])
def test_failed_recovery_refuses_completion(states, options, match):
    with pytest.raises(RuntimeError, match=match):
        a.rehearse(*states, health={}, **options)
