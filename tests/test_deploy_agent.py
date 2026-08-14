from pathlib import Path

import pytest

import deploy_agent


def app(tmp_path):
    return {"name": "demo", "enabled": True, "repo_path": str(tmp_path), "branch": "main",
            "restart_command": ["systemctl", "--user", "restart", "demo.service"],
            "health_url": "http://127.0.0.1:5000/health"}


def test_disabled_application_never_inspects_repository(tmp_path, monkeypatch):
    value = app(tmp_path) | {"enabled": False}
    monkeypatch.setattr(deploy_agent, "inspect_application", lambda *_: pytest.fail("should not inspect"))
    assert deploy_agent.deploy_application(value, False, deploy_agent.logging.getLogger())["status"] == "disabled"


def test_dirty_repository_is_blocked(tmp_path, monkeypatch):
    value = app(tmp_path) | {"auto_deploy": True}
    monkeypatch.setattr(deploy_agent, "inspect_application", lambda *_: {
        "repo": Path(tmp_path), "dirty": " M settings.py", "local": "a", "remote": "b", "update_available": True
    })
    with pytest.raises(deploy_agent.DeployError, match="local changes"):
        deploy_agent.deploy_application(value, False, deploy_agent.logging.getLogger())


def test_monitor_only_dirty_repository_reports_without_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy_agent, "inspect_application", lambda *_: {
        "repo": Path(tmp_path), "dirty": " M settings.py", "local": "a", "remote": "b", "update_available": True
    })
    result = deploy_agent.deploy_application(app(tmp_path), False, deploy_agent.logging.getLogger())
    assert result["status"] == "monitored_dirty"
    assert result["update_available"] is True


def test_dry_run_reports_update_without_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy_agent, "inspect_application", lambda *_: {
        "repo": Path(tmp_path), "dirty": "", "local": "a", "remote": "b", "update_available": True
    })
    monkeypatch.setattr(deploy_agent, "git", lambda *_: pytest.fail("must not merge"))
    result = deploy_agent.deploy_application(app(tmp_path), True, deploy_agent.logging.getLogger())
    assert result == {"name": "demo", "status": "update_available", "from": "a", "to": "b"}


def test_current_repository_does_not_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy_agent, "inspect_application", lambda *_: {
        "repo": Path(tmp_path), "dirty": "", "local": "a", "remote": "a", "update_available": False
    })
    monkeypatch.setattr(deploy_agent, "run", lambda *_: pytest.fail("must not restart"))
    assert deploy_agent.deploy_application(app(tmp_path), False, deploy_agent.logging.getLogger())["status"] == "current"


def test_execute_writes_status_file(tmp_path, monkeypatch):
    value = app(tmp_path) | {"auto_deploy": False}
    config = {"applications": [value], "lock_file": str(tmp_path / "lock"),
              "state_file": str(tmp_path / "status.json")}
    monkeypatch.setattr(deploy_agent, "deploy_application", lambda *_: {
        "name": "demo", "status": "current", "commit": "abc"
    })
    deploy_agent.execute(config, False, False)
    status = __import__("json").loads((tmp_path / "status.json").read_text())
    assert status["version"] == deploy_agent.VERSION
    assert status["applications"][0]["status"] == "current"
