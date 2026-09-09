from unittest.mock import Mock, patch
from pathlib import Path

import dashboard


def test_health_endpoint(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"applications": [], "dashboard_token": "secret"}')
    client = dashboard.create_app(config).test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["version"] == dashboard.VERSION


def test_unknown_application_update_is_404(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"applications": [], "dashboard_token": "secret"}')
    client = dashboard.create_app(config).test_client()
    header = {"Authorization": "Basic YWRtaW46c2VjcmV0"}
    assert client.post("/applications/missing/update", headers=header, data={"csrf_token": client.application.config["CSRF_TOKEN"]}).status_code == 404


def test_dashboard_requires_authentication(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"applications": [], "dashboard_token": "secret"}')
    client = dashboard.create_app(config).test_client()
    assert client.get("/").status_code == 401


def test_dashboard_refreshes_every_two_minutes(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"applications": [], "dashboard_token": "secret"}')
    client = dashboard.create_app(config).test_client()
    header = {"Authorization": "Basic YWRtaW46c2VjcmV0"}

    response = client.get("/", headers=header)

    assert response.status_code == 200
    assert b'<meta http-equiv="refresh" content="120">' in response.data


def test_library_dashboard_has_no_health_endpoint(tmp_path):
    import json
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"applications": [{"name": "research-core", "enabled": True,
        "kind": "library", "update_commands": [["pytest"]], "repo_path": "/tmp/library", "branch": "main"}], "dashboard_token": "secret"}))
    response = dashboard.create_app(config).test_client().get("/", headers={"Authorization": "Basic YWRtaW46c2VjcmV0"})
    assert response.status_code == 200


def test_service_action_runs_allowlisted_systemd_unit(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('''{"applications": [{
        "name": "example", "enabled": true, "auto_deploy": false,
        "repo_path": "/tmp/example", "branch": "main",
        "restart_command": ["systemctl", "--user", "restart", "example.service"],
        "health_url": "http://127.0.0.1:5999/health",
        "service_unit": "example.service"
    }], "dashboard_token": "secret"}''')
    import json
    value = json.loads(config.read_text())
    value['lock_file'] = str(tmp_path / 'deploy.lock')
    config.write_text(json.dumps(value))
    client = dashboard.create_app(config).test_client()
    header = {"Authorization": "Basic YWRtaW46c2VjcmV0"}

    with patch("dashboard.subprocess.run", return_value=Mock(returncode=0, stdout="", stderr="")) as run:
        response = client.post("/applications/example/service/start", headers=header, data={"csrf_token": client.application.config["CSRF_TOKEN"]})

    assert response.status_code == 302
    run.assert_called_once_with(
        ["systemctl", "--user", "start", "--", "example.service"],
        text=True, capture_output=True, timeout=30, check=False,
    )


def test_service_action_rejects_unconfigured_app(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('''{"applications": [{
        "name": "example", "enabled": true, "auto_deploy": false,
        "repo_path": "/tmp/example", "branch": "main",
        "restart_command": ["true"], "health_url": "http://127.0.0.1:5999/"
    }], "dashboard_token": "secret"}''')
    client = dashboard.create_app(config).test_client()
    header = {"Authorization": "Basic YWRtaW46c2VjcmV0"}

    assert client.post("/applications/example/service/start", headers=header, data={"csrf_token": client.application.config["CSRF_TOKEN"]}).status_code == 403


def service_client(tmp_path, **overrides):
    import json
    entry = {"name": "example", "enabled": True, "auto_deploy": True,
             "repo_path": "/tmp/example", "branch": "main", "restart_command": ["true"],
             "health_url": "http://127.0.0.1:5999/", "service_unit": "example.service"}
    entry.update(overrides)
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'applications': [entry], 'dashboard_token': 'secret',
                                  'lock_file': str(tmp_path / 'deploy.lock')}))
    client = dashboard.create_app(config).test_client()
    return client, {'Authorization': 'Basic YWRtaW46c2VjcmV0'}, {'csrf_token': client.application.config['CSRF_TOKEN']}


def test_service_controls_require_authentication_and_csrf(tmp_path):
    client, headers, data = service_client(tmp_path)
    with patch('dashboard.subprocess.run') as run:
        assert client.post('/applications/example/service/stop', data=data).status_code == 401
        assert client.post('/applications/example/service/stop', headers=headers).status_code == 403
        assert client.post('/applications/example/service/stop', headers=headers,
                           data={'csrf_token': 'wrong'}).status_code == 403
        assert client.post('/applications/example/update', headers=headers).status_code == 403
        run.assert_not_called()


def test_service_controls_reject_unknown_actions_and_disabled_apps(tmp_path):
    client, headers, data = service_client(tmp_path, enabled=False)
    with patch('dashboard.subprocess.run') as run:
        assert client.post('/applications/example/service/stop', headers=headers, data=data).status_code == 403
        assert client.post('/applications/example/service/enable', headers=headers, data=data).status_code == 404
        assert client.post('/applications/missing/service/start', headers=headers, data=data).status_code == 404
        run.assert_not_called()


def test_service_controls_do_not_interrupt_deployments(tmp_path):
    import fcntl
    client, headers, data = service_client(tmp_path)
    with (tmp_path / 'deploy.lock').open('w') as lock, patch('dashboard.subprocess.run') as run:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert client.post('/applications/example/service/restart', headers=headers, data=data).status_code == 409
        run.assert_not_called()


def test_missing_systemctl_does_not_break_dashboard(tmp_path):
    client, headers, data = service_client(tmp_path, health_url='')
    with patch('dashboard.subprocess.run', side_effect=FileNotFoundError('systemctl')):
        response = client.get('/', headers=headers)
        assert response.status_code == 200
        assert b'unknown' in response.data
        assert data['csrf_token'].encode() in response.data


def test_service_only_update_is_rejected(tmp_path):
    client, headers, data = service_client(tmp_path, deployment_enabled=False)
    with patch('dashboard.subprocess.run') as run:
        assert client.post('/applications/example/update', headers=headers, data=data).status_code == 403
        run.assert_not_called()
