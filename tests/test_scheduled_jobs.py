import json
import logging
from pathlib import Path

import pytest

import deploy_agent


def application(tmp_path, name="demo", jobs=None):
    return {
        "name": name,
        "enabled": True,
        "auto_deploy": False,
        "repo_path": str(tmp_path / name),
        "branch": "main",
        "restart_command": ["systemctl", "--user", "restart", f"{name}.service"],
        "health_url": "http://127.0.0.1:5000/health",
        "scheduled_jobs": jobs or [],
    }


def job(name="cleanup", **overrides):
    value = {"name": name, "enabled": True, "schedule": "daily", "time": "06:00",
             "command": ["./venv/bin/flask", "--app", "run.py", "cleanup"]}
    value.update(overrides)
    return value


def load(tmp_path, apps):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"applications": apps}))
    return deploy_agent.load_config(path)


def fake_systemd(monkeypatch):
    calls = []
    monkeypatch.setattr(deploy_agent, "run", lambda command, **kwargs: calls.append(command) or "")
    monkeypatch.setattr(deploy_agent, "systemctl_ok", lambda arguments: True)
    return calls


def test_valid_scheduled_job_config(tmp_path):
    config = load(tmp_path, [application(tmp_path, jobs=[job()])])
    assert config["applications"][0]["scheduled_jobs"][0]["name"] == "cleanup"


@pytest.mark.parametrize("overrides", [
    {"schedule": "daily", "time": "25:00"},
    {"schedule": "weekly", "weekday": "Funday", "time": "06:00"},
    {"schedule": "on-calendar", "on_calendar": ""},
    {"schedule": "every-second"},
])
def test_invalid_schedule_config(tmp_path, overrides):
    with pytest.raises(deploy_agent.DeployError):
        load(tmp_path, [application(tmp_path, jobs=[job(**overrides)])])


@pytest.mark.parametrize("unsafe", ["../escape", "Uppercase", "two words", "-leading", "trailing-"])
def test_invalid_unsafe_names(tmp_path, unsafe):
    with pytest.raises(deploy_agent.DeployError):
        load(tmp_path, [application(tmp_path, jobs=[job(name=unsafe)])])


def test_schedule_conversions():
    assert deploy_agent.schedule_to_on_calendar(job()) == "*-*-* 06:00:00"
    assert deploy_agent.schedule_to_on_calendar(job(schedule="hourly", minute=15)) == "*-*-* *:15:00"
    assert deploy_agent.schedule_to_on_calendar(
        job(schedule="weekly", weekday="Monday", time="07:30")) == "Mon *-*-* 07:30:00"
    assert deploy_agent.schedule_to_on_calendar(
        job(schedule="on-calendar", on_calendar="Mon..Fri *-*-* 08:00:00")) == "Mon..Fri *-*-* 08:00:00"


def test_generated_service_and_timer_content(tmp_path):
    app = application(tmp_path, jobs=[job(description="Safe cleanup", environment_file="~/.config/demo.env")])
    service_name, timer_name, service, timer = deploy_agent.render_scheduled_units(app, app["scheduled_jobs"][0])
    assert service_name == "uda-demo-cleanup.service"
    assert timer_name == "uda-demo-cleanup.timer"
    assert f'WorkingDirectory="{(tmp_path / "demo").resolve()}"' in service
    assert f'ExecStart="{(tmp_path / "demo/venv/bin/flask").resolve()}" "--app" "run.py" "cleanup"' in service
    assert "EnvironmentFile=" in service and "demo.env" in service
    assert "OnCalendar=*-*-* 06:00:00" in timer
    assert "Persistent=true" in timer
    assert "Unit=uda-demo-cleanup.service" in timer


def test_command_is_argument_based_and_never_uses_shell(tmp_path, monkeypatch):
    app = application(tmp_path, jobs=[job()])
    calls = []
    monkeypatch.setattr(deploy_agent.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)) or type("R", (), {"returncode": 0})())
    deploy_agent.systemctl_ok(["is-active", "--quiet", "uda-demo-cleanup.timer"])
    assert calls[0][0] == ["systemctl", "--user", "is-active", "--quiet", "uda-demo-cleanup.timer"]
    assert "shell" not in calls[0][1]


def test_idempotent_unit_generation(tmp_path, monkeypatch):
    app = application(tmp_path, jobs=[job()])
    config = {"applications": [app]}
    calls = fake_systemd(monkeypatch)
    first = deploy_agent.reconcile_scheduled_jobs(config, logging.getLogger(), tmp_path / "units")
    calls.clear()
    second = deploy_agent.reconcile_scheduled_jobs(config, logging.getLogger(), tmp_path / "units")
    assert len(first["changed"]) == 2
    assert second == {"changed": [], "removed": []}
    assert calls == []


def test_disabled_job_removes_obsolete_units(tmp_path, monkeypatch):
    unit_dir = tmp_path / "units"
    active = application(tmp_path, jobs=[job()])
    fake_systemd(monkeypatch)
    deploy_agent.reconcile_scheduled_jobs({"applications": [active]}, logging.getLogger(), unit_dir)
    removed = deploy_agent.reconcile_scheduled_jobs(
        {"applications": [application(tmp_path, jobs=[job(enabled=False)])]}, logging.getLogger(), unit_dir)
    assert sorted(removed["removed"]) == ["uda-demo-cleanup.service", "uda-demo-cleanup.timer"]
    assert not list(unit_dir.glob("uda-demo-cleanup.*"))


def test_unmanaged_similar_units_are_never_removed(tmp_path, monkeypatch):
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    foreign = unit_dir / "uda-foreign-job.timer"
    foreign.write_text("[Timer]\nOnCalendar=daily\n")
    fake_systemd(monkeypatch)
    deploy_agent.reconcile_scheduled_jobs({"applications": []}, logging.getLogger(), unit_dir)
    assert foreign.exists()


def test_multiple_jobs_apps_and_unit_isolation(tmp_path, monkeypatch):
    config = {"applications": [
        application(tmp_path, "alpha", [job("one"), job("two", schedule="hourly")]),
        application(tmp_path, "beta", [job("one")]),
    ]}
    fake_systemd(monkeypatch)
    deploy_agent.reconcile_scheduled_jobs(config, logging.getLogger(), tmp_path / "units")
    names = {path.name for path in (tmp_path / "units").iterdir()}
    assert names == {"uda-alpha-one.service", "uda-alpha-one.timer", "uda-alpha-two.service",
                     "uda-alpha-two.timer", "uda-beta-one.service", "uda-beta-one.timer"}


def test_status_reporting(tmp_path, monkeypatch):
    responses = iter([
        "ActiveState=active\nNextElapseUSecRealtime=Wed 2026-09-16 06:00:00 BST\nLastTriggerUSec=Tue 2026-09-15 06:00:00 BST",
        "Result=success",
    ])
    monkeypatch.setattr(deploy_agent, "run", lambda *args, **kwargs: next(responses))
    status = deploy_agent.scheduled_job_status(application(tmp_path), job())
    assert status["timer_active"] is True
    assert status["result"] == "success"
    assert status["service_unit"] == "uda-demo-cleanup.service"


def test_existing_deployment_function_does_not_execute_job(tmp_path, monkeypatch):
    value = application(tmp_path, jobs=[job()])
    monkeypatch.setattr(deploy_agent, "inspect_application", lambda *_: {
        "repo": Path(value["repo_path"]), "dirty": "", "local": "a", "remote": "a", "update_available": False})
    monkeypatch.setattr(deploy_agent, "run", lambda *_: pytest.fail("scheduled job or restart must not run"))
    assert deploy_agent.deploy_application(value, False, logging.getLogger())["status"] == "current"
