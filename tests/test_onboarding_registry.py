"""Disabled registry candidate and recovery plan tests."""
from copy import deepcopy

import pytest

from onboarding import OnboardingError
from onboarding_registry import inactive_registry_entry, preview_registry_diff, transaction_steps


def sample():
    plan = {"application": "demo", "commit_sha": "a" * 40,
            "branch": "main", "service_unit": "uda-demo.service",
            "port": 5200, "health_path": "/health", "group": "Development"}
    release = {"application": "demo", "commit_sha": "a" * 40,
               "status": "prepared_inactive",
               "release_path": "/tmp/releases/demo/aaaaaaaa"}
    return plan, release


def test_proposed_registry_entry_is_disabled_and_unpublished():
    plan, release = sample()
    entry = inactive_registry_entry(plan, release)
    assert entry["enabled"] is False
    assert entry["auto_deploy"] is False
    assert entry["deployment_enabled"] is False
    assert entry["proxy_enabled"] is False
    assert entry["github_reporting_enabled"] is False
    assert entry["health_url"] == "http://127.0.0.1:5200/health"


def test_registry_preview_does_not_change_original_registry():
    plan, release = sample()
    current = {"applications": [], "groups": ["Development"]}
    original = deepcopy(current)
    preview = preview_registry_diff(plan, release, current)
    assert current == original
    assert preview["registry_modified"] is False
    assert len(preview["proposed_registry"]["applications"]) == 1


@pytest.mark.parametrize("existing", [
    {"name": "demo"},
    {"name": "other", "service_unit": "uda-demo.service"},
    {"name": "other", "port": 5200},
])
def test_registry_conflicts_are_rejected(existing):
    plan, release = sample()
    with pytest.raises(OnboardingError, match="already registered"):
        preview_registry_diff(plan, release, {"applications": [existing]})


def test_registry_refuses_inconsistent_release():
    plan, release = sample()
    release["commit_sha"] = "b" * 40
    with pytest.raises(OnboardingError, match="SHA"):
        inactive_registry_entry(plan, release)


def test_transactions_have_compensation_steps():
    sequence = transaction_steps()
    names = [step["step"] for step in sequence]
    assert names.index("take_backup") < names.index("write_registry")
    assert names.index("start_loopback_and_health_check") < names.index("refresh_caddy")
    assert all(step.get("rollback") for step in sequence)
    assert names[-1] == "publish_github_deployment"
