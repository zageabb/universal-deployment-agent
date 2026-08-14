from pathlib import Path

import dashboard


def test_health_endpoint(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"applications": [], "dashboard_token": "secret"}')
    client = dashboard.create_app(config).test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["version"] == "1.1.0"


def test_unknown_application_update_is_404(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"applications": [], "dashboard_token": "secret"}')
    client = dashboard.create_app(config).test_client()
    header = {"Authorization": "Basic YWRtaW46c2VjcmV0"}
    assert client.post("/applications/missing/update", headers=header).status_code == 404


def test_dashboard_requires_authentication(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"applications": [], "dashboard_token": "secret"}')
    client = dashboard.create_app(config).test_client()
    assert client.get("/").status_code == 401
