"""Read-only host acceptance review: no real systemd is contacted in tests."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from onboarding_v2_host_readiness import inspect_host, _read_status, main


def fixture(tmp_path, *, version="22.04", states=None, failure=None):
    release = tmp_path / "os-release"
    release.write_text(f'NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="{version}"\n')
    states = states or {}
    calls = []

    def runner(command, **kw):
        calls.append(command)
        assert command[:3] == ["systemctl", "--user", "show"]
        assert "--" in command and len(command[command.index("--") + 1:]) == 1
        assert kw == {"capture_output": True, "text": True,
                      "check": False, "timeout": 8}
        unit = command[-1]
        if unit == failure:
            return SimpleNamespace(returncode=1, stdout="", stderr="unavailable")
        state = states.get(unit, "inactive")
        return SimpleNamespace(returncode=0, stdout=(
            f"LoadState=loaded\nActiveState={state}\nSubState=dead\n"
            "UnitFileState=enabled\nNextElapseUSecRealtime=Fri 2026-11-20 14:00:00 GMT\n"
        ), stderr="")
    return release, runner, calls


def test_active_timers_block_acceptance(tmp_path):
    release, runner, calls = fixture(tmp_path, states={
        "deployment-agent.timer": "active",
        "uda-proxy-refresh.timer": "active",
    })
    result = inspect_host(os_release=release, runner=runner)
    assert result["ubuntu_version"] == "22.04"
    assert "production_deployment_timer_active" in result["maintenance_isolation_blockers"]
    assert "production_proxy_timer_active" in result["maintenance_isolation_blockers"]
    assert not result["ready_for_isolated_test_scheduling"]
    assert result["deployment_allowed"] is False
    assert result["timer_mutation_allowed"] is False
    assert result["production_activation_allowed"] is False
    assert result["lock_holder_verified"] is False
    assert len(calls) == 4


def test_active_oneshot_blocks_even_if_timers_inactive(tmp_path):
    release, runner, calls = fixture(tmp_path, states={
        "deployment-agent.service": "activating",
    })
    result = inspect_host(os_release=release, runner=runner)
    assert "deployment_oneshot_active" in result["maintenance_isolation_blockers"]
    assert not result["ready_for_isolated_test_scheduling"]


def test_24_04_supported_but_never_grants_install(tmp_path):
    release, runner, calls = fixture(tmp_path, version="24.04")
    result = inspect_host(os_release=release, runner=runner)
    assert result["ready_for_isolated_test_scheduling"] is True
    assert result["maintenance_isolation_blockers"] == []
    assert not result["deployment_allowed"]
    assert not result["lock_holder_verified"]


def test_wrong_os_and_unknown_timer_fail_closed(tmp_path):
    release, runner, calls = fixture(tmp_path, version="20.04",
                                     failure="uda-proxy-refresh.timer")
    result = inspect_host(os_release=release, runner=runner)
    assert "unsupported_ubuntu" in result["maintenance_isolation_blockers"]
    assert "timer_inspection_incomplete" in result["maintenance_isolation_blockers"]
    assert result["ready_for_isolated_test_scheduling"] is False


def test_allowlist_blocks_arbitrary_user_service(tmp_path):
    release, runner, calls = fixture(tmp_path)
    with pytest.raises(ValueError, match="Unapproved"):
        _read_status("sheetbridge.service", runner)
    assert calls == []


def test_unknown_or_oversized_output_is_fail_closed(tmp_path):
    release, runner, calls = fixture(tmp_path)
    def oversized(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout="A" * 5000, stderr="")
    result = inspect_host(os_release=release, runner=oversized)
    assert not result["ready_for_isolated_test_scheduling"]
    assert "timer_inspection_incomplete" in result["maintenance_isolation_blockers"]


def test_report_contains_no_config_or_secret_values(tmp_path):
    release, runner, calls = fixture(tmp_path)
    result = inspect_host(os_release=release, runner=runner)
    encoded = json.dumps(result)
    assert "dashboard_token" not in encoded
    assert "proxy_assertion" not in encoded
    assert "password" not in encoded.lower()
    assert set(result["units"]) == {
        "deployment-agent.timer", "uda-proxy-refresh.timer",
        "deployment-agent.service", "uda-proxy-refresh.service",
    }
