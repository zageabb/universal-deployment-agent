import json
from pathlib import Path

import proxy_migration_agent as agent


def app(tmp_path, **values):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests/test_uda_subpath.py").write_text("def test_marker(): pass\n")
    base = {
        "name": "example",
        "enabled": True,
        "repo_path": str(repo),
        "branch": "main",
        "restart_command": ["true"],
        "health_url": "http://127.0.0.1:5050/health",
        "group": "TAIJU",
    }
    base.update(values)
    return base


def test_origin_uses_only_health_origin(tmp_path):
    assert agent.origin_for(app(tmp_path)) == "http://127.0.0.1:5050"


def test_python_falls_back_to_update_pip_sibling(tmp_path):
    value = app(tmp_path, update_commands=[[str(tmp_path / "venv/bin/pip"), "install"]])
    python = tmp_path / "venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    assert agent.python_for(value, Path(value["repo_path"])) == python


def test_write_config_is_valid_and_preserves_mode(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{}\n")
    path.chmod(0o600)
    agent.write_config(path, {"applications": []})
    assert json.loads(path.read_text()) == {"applications": []}
    assert path.stat().st_mode & 0o777 == 0o600
