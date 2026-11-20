"""In-memory failure-injection tests for the activation transaction protocol."""
from unittest.mock import Mock
import uuid

import pytest

from onboarding import OnboardingError
from onboarding_transaction import (
    STEPS, delivery_after_activation, execute_transaction,
)


def fixture():
    return (
        {"application": "demo", "commit_sha": "a" * 40, "stage_only": True},
        {"application": "demo", "commit_sha": "a" * 40, "status": "prepared_inactive"},
    )


class FakeAdapter:
    def __init__(self, fail_at=None, rollback_fail=None, snapshot=True):
        self.events = []
        self.fail_at = fail_at
        self.rollback_fail = rollback_fail
        self.snapshot = snapshot
        self.locked = False
        self.state = {"service": False, "start": False, "registry": False,
                      "proxy": False, "attestation": False}

    def _event(self, name, compensation=None):
        self.events.append(name)
        if compensation:
            self.state[compensation] = True
        if self.fail_at == name:
            raise RuntimeError(f"simulated {name} failure")

    def acquire_lock(self):
        self.locked = True
        self._event("lock")

    def release_lock(self):
        self.locked = False
        self.events.append("unlock")

    def capture_snapshot(self, transaction_id):
        self._event("snapshot")
        return dict(self.state) if self.snapshot else None

    def preflight(self, plan, release):
        self._event("preflight")

    def configure_service(self, plan, release):
        self._event("configure_service", "service")

    def start_service(self, plan):
        self._event("start_service", "start")

    def verify_health(self, plan, release):
        self._event("verify_health")

    def register_application(self, plan, release):
        self._event("register_application", "registry")

    def publish_proxy(self, plan):
        self._event("publish_proxy", "proxy")

    def verify_authentication(self, plan):
        self._event("verify_authentication")

    def verify_runtime_sha(self, plan, release):
        self._event("verify_runtime_sha")

    def record_attestation(self, plan, release):
        self._event("record_attestation", "attestation")

    def compensate(self, step, snapshot, plan):
        self.events.append("undo_" + step)
        if self.rollback_fail == step:
            raise RuntimeError("undo refused")
        self.state[step] = snapshot[step]


def execute(adapter, journal=None):
    plan, release = fixture()
    return execute_transaction(
        plan, release, adapter, transaction_id=str(uuid.uuid4()),
        explicitly_approved=True, production_enablement=True, journal=journal
    )


def test_refuses_execution_without_separate_enablement():
    plan, release = fixture()
    adapter = FakeAdapter()
    with pytest.raises(OnboardingError, match="disabled"):
        execute_transaction(plan, release, adapter, transaction_id=str(uuid.uuid4()))
    assert adapter.events == []


def test_completed_flow_checks_health_and_auth_before_attestation():
    adapter = FakeAdapter()
    events = []
    result = execute(adapter, journal=lambda state: events.append(state))
    assert result.state == "completed"
    assert result.error is None
    assert result.executed == [step for step, _ in STEPS]
    assert adapter.events.index("verify_health") < adapter.events.index("publish_proxy")
    assert adapter.events.index("verify_authentication") < adapter.events.index("record_attestation")
    assert adapter.locked is False
    assert all(adapter.state.values())
    assert events[-1]["state"] == "completed"


@pytest.mark.parametrize("failure", [step for step, _ in STEPS])
def test_each_activation_failure_triggers_reverse_compensation(failure):
    adapter = FakeAdapter(fail_at=failure)
    result = execute(adapter)
    assert result.state == "rolled_back"
    assert adapter.state == {"service": False, "start": False, "registry": False,
                             "proxy": False, "attestation": False}
    assert adapter.locked is False
    assert result.error and failure in result.error


def test_partial_proxy_write_rolls_back_proxy_then_registry_and_service():
    adapter = FakeAdapter(fail_at="publish_proxy")
    result = execute(adapter)
    assert result.state == "rolled_back"
    order = [name for name in adapter.events if name.startswith("undo_")]
    assert order == ["undo_proxy", "undo_registry", "undo_start", "undo_service"]


def test_rollback_failure_is_never_reported_as_success():
    adapter = FakeAdapter(fail_at="verify_authentication", rollback_fail="proxy")
    result = execute(adapter)
    assert result.state == "rollback_failed"
    assert any("proxy" in message for message in result.rollback_errors)
    assert "undo_registry" in adapter.events
    assert adapter.locked is False


def test_snapshot_failure_never_mutates():
    adapter = FakeAdapter(snapshot=False)
    result = execute(adapter)
    assert result.state == "rolled_back"
    assert adapter.events == ["lock", "snapshot", "unlock"]


def test_missing_preflight_stops_mutations():
    adapter = FakeAdapter(fail_at="preflight")
    result = execute(adapter)
    assert result.state == "rolled_back"
    assert "configure_service" not in adapter.events


def test_failed_github_delivery_does_not_uninstall_healthy_application():
    adapter = FakeAdapter()
    result = execute(adapter)
    response = delivery_after_activation(
        result, lambda: (_ for _ in ()).throw(RuntimeError("GitHub 503"))
    )
    assert response["github"] == "delivery_failed"
    assert adapter.state["service"] is True


def test_github_publication_not_called_after_rollback():
    adapter = FakeAdapter(fail_at="verify_health")
    result = execute(adapter)
    callback = Mock()
    with pytest.raises(OnboardingError, match="uncommitted"):
        delivery_after_activation(result, callback)
    callback.assert_not_called()
