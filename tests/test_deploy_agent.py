from unittest.mock import Mock
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


def deployment_fixture(tmp_path, monkeypatch):
    value = app(tmp_path) | {"auto_deploy": True, "python": str(tmp_path / '.venv/bin/python')}
    monkeypatch.setattr(deploy_agent, "inspect_application", lambda *_: {
        "repo": tmp_path, "dirty": "", "local": "a", "remote": "b", "update_available": True})
    return value


@pytest.mark.parametrize('name', ['tender-designer', 'internet-pricing', 'should-cost-intelligence'])
def test_python_install_precedes_setup_and_existing_restart(tmp_path, monkeypatch, name):
    value = deployment_fixture(tmp_path, monkeypatch) | {'name': name, 'update_commands': [['setup']]}
    calls = []
    monkeypatch.setattr(deploy_agent, 'git', lambda *args: calls.append(list(args[1:])))
    monkeypatch.setattr(deploy_agent, 'run', lambda cmd, **kw: calls.append(cmd) or '')
    monkeypatch.setattr(deploy_agent, 'health_check', lambda *args: calls.append(['health']))
    monkeypatch.setattr(deploy_agent, 'diagnostics', lambda *args: {})
    deploy_agent.deploy_application(value, False, deploy_agent.logging.getLogger())
    assert calls == [['merge', '--ff-only', 'origin/main'],
                     [value['python'], '-m', 'pip', 'install', '--upgrade', '--force-reinstall', '-r', 'requirements.txt'],
                     ['setup'], value['restart_command'], ['health']]


@pytest.mark.parametrize('recovery_fails', [False, True])
def test_failed_pip_never_restarts(tmp_path, monkeypatch, recovery_fails):
    value = deployment_fixture(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(deploy_agent, 'git', lambda *args: calls.append(list(args[1:])))
    count = 0
    def run(cmd, **kw):
        nonlocal count
        calls.append(cmd)
        count += 1
        if count == 1 or recovery_fails:
            raise deploy_agent.DeployError('pip network failure')
    monkeypatch.setattr(deploy_agent, 'run', run)
    with pytest.raises(deploy_agent.DeployError, match='Dependency installation failed.*pip network failure'):
        deploy_agent.deploy_application(value, False, deploy_agent.logging.getLogger())
    assert value['restart_command'] not in calls
    assert ['reset', '--hard', 'a'] in calls
    assert count == 2


def test_library_validates_without_service(tmp_path, monkeypatch):
    import json
    value = deployment_fixture(tmp_path, monkeypatch) | {'kind': 'library', 'update_commands': [['pytest']]}
    value.pop('python')
    value.pop('restart_command')
    value.pop('health_url')
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'applications': [value]}))
    deploy_agent.load_config(config)
    calls = []
    monkeypatch.setattr(deploy_agent, 'git', lambda *a: '')
    monkeypatch.setattr(deploy_agent, 'run', lambda cmd, **kw: calls.append(cmd) or '')
    monkeypatch.setattr(deploy_agent, 'health_check', lambda *a: pytest.fail('library has no web service'))
    assert deploy_agent.deploy_application(value, False, deploy_agent.logging.getLogger())['status'] == 'deployed'
    assert calls == [['pytest']]


def test_health_failure_restores_dependencies_before_restart(tmp_path, monkeypatch):
    value = deployment_fixture(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(deploy_agent, 'git', lambda *a: calls.append(list(a[1:])))
    monkeypatch.setattr(deploy_agent, 'run', lambda cmd, **kw: calls.append(cmd))
    def health(*a):
        if calls.count(value['restart_command']) == 1:
            raise deploy_agent.DeployError('unhealthy')
    monkeypatch.setattr(deploy_agent, 'health_check', health)
    with pytest.raises(deploy_agent.DeployError, match='unhealthy'):
        deploy_agent.deploy_application(value, False, deploy_agent.logging.getLogger())
    assert calls[-3:] == [['reset', '--hard', 'a'], deploy_agent.dependency_command(value), value['restart_command']]


def test_service_only_application_skips_git_inspection(tmp_path):
    app = {
        "name": "legacy-app",
        "enabled": True,
        "deployment_enabled": False,
        "repo_path": str(tmp_path / "not-a-repository"),
        "branch": "main",
        "restart_command": ["true"],
        "health_url": "http://127.0.0.1:5999/",
    }

    result = deploy_agent.deploy_application(app, dry_run=False, logger=Mock())

    assert result == {"name": "legacy-app", "status": "service_only"}
