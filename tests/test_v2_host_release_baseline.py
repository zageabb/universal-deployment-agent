"""Read-only host baseline unit tests; no real systemctl calls."""
from __future__ import annotations

import json
import subprocess

from tools.v2_host_release_baseline import (
    PROPERTIES, SERVICES, TIMERS, collect, read_unit,
)


def test_only_systemctl_user_show_is_used():
    commands = []

    def fake(cmd, **kwargs):
        commands.append(cmd)
        return subprocess.CompletedProcess(
            cmd, 0,
            "LoadState=loaded\nActiveState=active\nSubState=waiting\n"
            "UnitFileState=enabled\nResult=success\n", "")

    report = collect(runner=fake)
    assert len(commands) == len(SERVICES) + len(TIMERS)
    assert all(cmd[:4] == [
        "systemctl", "--user", "show", "--no-pager"] for cmd in commands)
    assert all(cmd[4] == "--property=" + ",".join(PROPERTIES)
               for cmd in commands)
    assert report["unit_metadata_collected"] == len(commands)
    assert report["timer_state_changed"] is False
    assert report["service_action_performed"] is False
    assert report["production_upgrade_authorized"] is False
    assert report["caddy_health_verified"] is False


def test_command_error_is_reported_without_claiming_success():
    def fake(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "synthetic secret")
    report = collect(runner=fake)
    assert report["unit_metadata_collected"] == 0
    assert all(item["observation"] == "unavailable"
               for item in report["units"])
    assert "synthetic secret" not in json.dumps(report)


def test_missing_required_properties_is_incomplete():
    def fake(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, "ActiveState=active\n", "")
    result = read_unit("deployment-agent.timer", runner=fake)
    assert result["observation"] == "incomplete"


def test_timeouts_do_not_trigger_retry_or_mutation():
    calls = []

    def fake(cmd, **kwargs):
        calls.append(cmd)
        raise subprocess.TimeoutExpired(cmd, 10)
    result = read_unit("deployment-agent.timer", runner=fake)
    assert result["observation"] == "unavailable"
    assert len(calls) == 1
