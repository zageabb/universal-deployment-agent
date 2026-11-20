"""Disposable installed-runtime smoke without executing install.sh.

Copies only explicitly declared install sources to a temporary directory and
starts a subprocess with isolated Python module search. No systemd, Docker,
Git, network listeners, production config, or installer calls.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _declared_install_sources(script: str) -> set[str]:
    # Source paths from literal install commands plus the review-only module
    # for-loop in install.sh. An unknown shell layout must fail closed.
    paths = set(re.findall(r'"\$SOURCE_DIR/([A-Za-z0-9_./-]+)"', script))
    assert script.count("for module in ") == 1
    block = script.split("for module in ", 1)[1].split("\ndo\n", 1)[0]
    assert block
    paths.update(re.findall(r'[A-Za-z0-9_]+\.py', block))
    return paths


@pytest.fixture
def disposable_runtime(tmp_path):
    script = (ROOT / "install.sh").read_text(encoding="utf-8")
    runtime = tmp_path / "installed-runtime"
    runtime.mkdir(mode=0o700)
    paths = _declared_install_sources(script)
    assert len(paths) >= 40  # refuse a silently gutted installer manifest
    for relative in sorted(paths):
        source = ROOT / relative
        assert source.is_file(), f"installer references missing asset: {relative}"
        assert not source.is_symlink(), relative
        destination = runtime / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    # A real installer creates the module file at DATA_DIR, not a literal
    # "$module" subpath; captured files above are the installed layout.
    assert (runtime / "dashboard.py").exists()
    assert (runtime / "tools/validate_v2_only.py").exists()
    assert (runtime / "templates/approvals.html").exists()
    assert (runtime / "schemas/uda-manifest-v2.schema.json").exists()
    assert not (runtime / "install.sh").exists()
    assert not (runtime / ".git").exists()
    return runtime


def test_disposable_runtime_loads_dashboard_and_review_views(disposable_runtime, tmp_path):
    config_dir = tmp_path / "private-config"
    config_dir.mkdir(mode=0o700)
    config_path = config_dir / "config.json"
    config_path.write_text(json.dumps({
        "dashboard_token": "disposable-smoke-token-not-a-real-secret",
        "applications": [],
    }), encoding="utf-8")
    config_path.chmod(0o600)

    # -I ignores PYTHONPATH and user site-packages; the only application code
    # on sys.path comes from the disposable runtime, never the source checkout.
    child = textwrap.dedent("""
        import importlib
        import json
        from pathlib import Path
        import sys

        runtime = Path(sys.argv[1]).resolve()
        config_path = Path(sys.argv[2]).resolve()
        sys.path.insert(0, str(runtime))
        dashboard = importlib.import_module("dashboard")
        deploy_agent = importlib.import_module("deploy_agent")
        validator = importlib.import_module("uda_manifest_v2_validate")
        assert Path(dashboard.__file__).resolve().parent == runtime
        assert Path(deploy_agent.__file__).resolve().parent == runtime
        assert validator.SCHEMA.is_file()
        app = dashboard.create_app(config_path)
        client = app.test_client()
        assert client.get("/health").status_code == 200
        headers = {
            "Authorization": "Basic YWRtaW46ZGlzcG9zYWJsZS1zbW9rZS10b2tlbi1ub3QtYS1yZWFsLXNlY3JldA=="
        }
        for route, expected in (
            ("/", b"html"),
            ("/onboarding", b"html"),
            ("/approvals", b"Approval Centre"),
        ):
            response = client.get(route, headers=headers)
            assert response.status_code == 200, (route, response.status_code)
            assert expected in response.data, route
        # No review credentials configured: every write remains denied.
        assert client.post("/approvals/request", headers=headers).status_code == 403
        print(json.dumps({
            "status": "PASS", "runtime_isolated": True,
            "views": ["dashboard", "onboarding", "approvals"],
            "host_services_modified": False, "deployment_allowed": False,
        }))
    """)
    completed = subprocess.run(
        [sys.executable, "-I", "-c", child, str(disposable_runtime), str(config_path)],
        cwd=disposable_runtime, text=True, capture_output=True,
        timeout=25, check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert completed.returncode == 0, (
        f"disposable runtime process failed: {completed.stderr[-2500:]}"
    )
    assert json.loads(completed.stdout.strip())["status"] == "PASS"


def test_disposable_runtime_has_no_host_service_or_config_payload(disposable_runtime):
    assert not (disposable_runtime / "config.json").exists()
    assert not (disposable_runtime / "deployment-agent.service").exists()
    assert not (disposable_runtime / "install.sh").exists()
    assert all(
        not p.is_symlink() for p in disposable_runtime.rglob("*")
    )
