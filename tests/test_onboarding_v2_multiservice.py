"""Failure injection for V2-003 in-memory multi-service transaction engine.

All systemd-like operations are fake; no real host components are touched.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from onboarding import OnboardingError
from onboarding_v2_multiservice import simulate_multiservice_release

ROOT = Path(__file__).resolve().parents[1]


def document():
    return yaml.safe_load((ROOT / "examples" / "uda-v2-multi-service.yaml").read_text())


class FakeUnits:
    def __init__(self, *, failing=None, unhealthy=None, rollback_failure=None):
        self.failing = failing
        self.unhealthy = set(unhealthy or ())
        self.rollback_failure = rollback_failure
        self.events = []
        self.state = {"web": "old", "mailbox": "old"}
        self.locked = False

    def do(self, action, name=None):
        label = f"{action}:{name}" if name else action
        self.events.append(label)
        if label == self.failing or label == self.rollback_failure:
            raise RuntimeError("simulated callback failure")

    def acquire_lock(self):
        self.locked = True
        self.do("acquire_lock")

    def release_lock(self):
        self.locked = False
        self.do("release_lock")

    def capture_snapshot(self, name):
        self.do("snapshot", name)
        return self.state[name]

    def configure(self, name, snapshot):
        self.state[name] = "configured"
        self.do("configure", name)

    def start(self, name):
        self.state[name] = "running"
        self.do("start", name)

    def check_health(self, name, health_type):
        assert health_type in {"http", "process"}
        self.do("probe", name)
        return name not in self.unhealthy

    def stop(self, name):
        self.state[name] = "stopped"
        self.do("stop", name)

    def restore(self, name, snapshot):
        self.state[name] = snapshot
        self.do("restore", name)


def run(adapter, journal=None):
    records = [] if journal is None else journal
    result = simulate_multiservice_release(
        document(), adapter, journal=records.append,
        simulation_only=True,
    )
    return result, records


def test_successful_graph_order_aggregate_health_and_no_activation():
    fake = FakeUnits()
    result, records = run(fake)
    assert result.state == "healthy"
    assert result.order == ["web", "mailbox"]
    assert result.healthy == ["web", "mailbox"]
    assert not result.degraded
    assert result.as_dict()["production_activation_allowed"] is False
    assert fake.state == {"web": "running", "mailbox": "running"}
    assert fake.events.index("configure:web") < fake.events.index("configure:mailbox")
    assert fake.events.index("start:web") < fake.events.index("start:mailbox")
    assert fake.events.index("probe:web") < fake.events.index("probe:mailbox")
    assert len([x for x in records if x["events"][-1].startswith("intent:")]) == 4
    assert not any("entrypoint" in str(x) or "MAIL_APP_PASSWORD" in str(x) for x in records)


def test_worker_failure_marks_app_degraded_even_if_web_http_healthy():
    fake = FakeUnits(unhealthy={"mailbox"})
    result, _ = run(fake)
    assert result.state == "degraded"
    assert result.healthy == ["web"]
    assert result.degraded == ["mailbox"]
    assert "probe:web" in fake.events
    assert not result.error_type


def test_required_web_health_failure_rolls_back_both_services():
    fake = FakeUnits(unhealthy={"web"})
    result, records = run(fake)
    assert result.state == "rolled_back"
    assert result.error_type == "OnboardingError"
    assert fake.state == {"web": "old", "mailbox": "old"}
    assert fake.events.index("stop:mailbox") < fake.events.index("stop:web")
    assert fake.events.index("restore:mailbox") < fake.events.index("restore:web")
    assert records[-1]["state"] == "rolled_back"
    assert not result.pending_undo


@pytest.mark.parametrize("fail", [
    "configure:web", "configure:mailbox", "start:web", "start:mailbox",
    "probe:web", "probe:mailbox",
])
def test_partial_mutation_always_compensated_in_reverse_order(fail):
    fake = FakeUnits(failing=fail)
    result, _ = run(fake)
    assert result.state == "rolled_back"
    assert fake.state == {"web": "old", "mailbox": "old"}
    assert fake.locked is False
    assert not result.pending_undo


def test_missing_snapshot_prevents_any_configuration():
    fake = FakeUnits()
    fake.capture_snapshot = lambda name: None if name == "mailbox" else "old"
    result, _ = run(fake)
    assert result.state == "rolled_back"
    assert all(not e.startswith("configure:") for e in fake.events)
    assert fake.state == {"web": "old", "mailbox": "old"}


def test_failed_journal_before_first_mutation_prevents_writes():
    fake = FakeUnits()
    def fail(_record):
        raise OSError("journal down")
    result = simulate_multiservice_release(document(), fake,
        journal=fail, simulation_only=True)
    assert all(not e.startswith(("configure:", "start:")) for e in fake.events)
    assert result.state == "rollback_failed"
    assert fake.locked is False


def test_failed_rollback_is_never_reported_as_success():
    fake = FakeUnits(failing="probe:web", rollback_failure="restore:web")
    result, _ = run(fake)
    assert result.state == "rollback_failed"
    assert "restore:web" in result.pending_undo
    assert "restore:web" in result.rollback_errors
    assert "restore:mailbox" in result.compensated


def test_no_approval_from_repository_manifest_is_accepted():
    fake = FakeUnits()
    with pytest.raises(OnboardingError, match="simulation-only"):
        simulate_multiservice_release(document(), fake, journal=lambda _: None)
    assert fake.events == []


@pytest.mark.parametrize("mutate", [
    lambda d: d["deployment"].update(strategy="hybrid"),
    lambda d: d.update(containers=[{"name": "container", "image": "invalid"}]),
    lambda d: d.update(capabilities=[{"name": "discovery", "kind": "network-discovery",
                                       "approval": "explicit", "enabled_by_default": False}]),
    lambda d: d.update(databases=[{"name": "db", "engine": "postgresql",
                                   "connection_secret": "DATABASE_URL"}]),
])
def test_only_supported_systemd_service_graphs_can_be_simulated(mutate):
    data = document()
    mutate(data)
    fake = FakeUnits()
    with pytest.raises(OnboardingError):
        simulate_multiservice_release(data, fake, journal=lambda _: None,
                                      simulation_only=True)
    assert fake.events == []


def test_graph_cycle_fails_before_callbacks():
    data = document()
    data["services"][0]["depends_on"] = ["mailbox"]
    fake = FakeUnits()
    with pytest.raises(OnboardingError, match="Invalid"):
        simulate_multiservice_release(data, fake, journal=lambda _: None,
                                      simulation_only=True)
    assert fake.events == []
