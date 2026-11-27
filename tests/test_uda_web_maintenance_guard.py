import json
import pytest
from flask import Flask, abort
import deploy_agent as d
import dashboard
import home


@pytest.fixture
def config(tmp_path):
    value = {"lock_file": str(tmp_path / "deploy.lock"), "applications": [],
             "dashboard_token": "fixture-token", "portal_auth_enabled": False}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value))
    return path, value


@pytest.mark.parametrize("factory", [dashboard.create_app, home.create_app])
@pytest.mark.parametrize("method,path", [("GET", "/health"), ("POST", "/"), ("GET", "/")])
def test_exclusive_blocks_web_request(config, factory, method, path):
    cfg_path, cfg = config
    app = factory(cfg_path)
    with d.maintenance_lock(cfg, exclusive=True):
        assert app.test_client().open(path, method=method).status_code == 503
    assert app.test_client().get("/health").status_code == 200


def test_guard_held_through_handler_and_teardown(config):
    cfg_path, cfg = config
    app = Flask(__name__)
    d.register_web_maintenance_guard(app, cfg_path)

    @app.get("/")
    def handler():
        with pytest.raises(d.DeployError, match="maintenance lock busy"):
            with d.maintenance_lock(cfg, exclusive=True):
                pytest.fail("exclusive acquired")
        abort(400)

    assert app.test_client().get("/").status_code == 400
    with d.maintenance_lock(cfg, exclusive=True):
        pass


def test_guard_released_after_exception(config):
    cfg_path, cfg = config
    app = Flask(__name__)
    app.testing = True
    d.register_web_maintenance_guard(app, cfg_path)

    @app.get("/")
    def handler():
        raise RuntimeError("fixture")

    with pytest.raises(RuntimeError, match="fixture"):
        app.test_client().get("/")
    with d.maintenance_lock(cfg, exclusive=True):
        pass


def test_verification_get_blocked(config):
    cfg_path, cfg = config
    app = home.create_app(cfg_path)
    with d.maintenance_lock(cfg, exclusive=True):
        assert app.test_client().get("/verify/fixture-token").status_code == 503
