"""Filesystem activation integration tests using injectable systemd/Caddy spies.

No Linux services, real proxy, database or network are changed.
"""
import json
from pathlib import Path
import uuid

import pytest

from onboarding_release import prepare_release
from onboarding_adapter import LocalActivationAdapter
from onboarding_transaction import execute_transaction


def fixture(tmp_path, *, fail=None):
    sha = "a" * 40
    stage_root = tmp_path / "staging"
    stage_root.mkdir()
    checkout = stage_root / "demo-aaaaaaaaaaaa"
    checkout.mkdir()
    (checkout / "app.py").write_text("pass\n")
    release_root = tmp_path / "releases"
    release_root.mkdir()
    release = prepare_release({
        "application": "demo", "repository": "zageabb/demo",
        "commit_sha": sha, "staged_path": str(checkout),
    }, stage_root, release_root)
    plan = {
        "application": "demo", "commit_sha": sha, "branch": "main",
        "stage_only": True, "requires_approval": True, "runtime": "python",
        "service_unit": "uda-demo.service", "port": 5200,
        "health_path": "/health", "proxy_path": "/apps/demo/",
        "entrypoint_pending_approval": ["python", "app.py"],
        "required_environment": [],
    }
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"applications": [], "public_base_url": "https://example.test",
                                    "dashboard_token": "test"}))
    unit = tmp_path / "uda-demo.service"
    proxy = tmp_path / "Caddyfile"
    attestation = tmp_path / "demo.sha"
    envfile = tmp_path / "app.env"
    envfile.write_text("PLACEHOLDER=x\n")
    envfile.chmod(0o600)
    events = []
    state = {"running": False}

    def operate(name):
        events.append(name)
        if name == fail:
            raise RuntimeError("simulated " + name)

    def start(unit):
        state["running"] = True
        operate("start")

    def stop(unit):
        state["running"] = False
        operate("stop")

    def reload():
        operate("reload_proxy")

    def health(url):
        assert state["running"]
        assert url == "http://127.0.0.1:5200/health"
        operate("health")

    def auth(path):
        assert path == "/apps/demo/"
        operate("auth")

    def runtime(name):
        operate("runtime")
        return sha

    adapter = LocalActivationAdapter(
        registry_path=registry, unit_path=unit, proxy_path=proxy,
        attestation_path=attestation, environment_path=envfile,
        lock_path=tmp_path / "uda.lock",
        service_start=start, service_stop=stop,
        proxy_reload=reload, health_probe=health,
        auth_probe=auth, runtime_probe=runtime,
        service_exists=lambda _: False, port_available=lambda _: True,
    )
    return plan, release, adapter, registry, unit, proxy, attestation, state, events


def activate(plan, release, adapter):
    return execute_transaction(
        plan, release, adapter, transaction_id=str(uuid.uuid4()),
        explicitly_approved=True, production_enablement=True
    )


def test_adapter_commits_only_after_health_auth_and_runtime(tmp_path):
    plan, release, adapter, registry, unit, proxy, receipt, state, events = fixture(tmp_path)
    result = activate(plan, release, adapter)
    assert result.state == "completed", result.as_dict()
    assert state["running"] is True
    apps = json.loads(registry.read_text())["applications"]
    assert len(apps) == 1
    assert apps[0]["name"] == "demo"
    assert apps[0]["proxy_enabled"] is True
    assert "forward_auth" in proxy.read_text()
    assert "ExecStart=" in unit.read_text()
    assert receipt.read_text().strip() == plan["commit_sha"]
    assert events.index("health") < events.index("reload_proxy") < events.index("auth") < events.index("runtime")


@pytest.mark.parametrize("failure", ["start", "health", "reload_proxy", "auth", "runtime"])
def test_adapter_restores_original_bytes_on_partial_failure(tmp_path, failure):
    plan, release, adapter, registry, unit, proxy, receipt, state, events = fixture(
        tmp_path, fail=failure
    )
    before = registry.read_bytes()
    result = activate(plan, release, adapter)
    assert result.state in {"rolled_back", "rollback_failed"}
    assert registry.read_bytes() == before
    assert not unit.exists()
    assert not receipt.exists()
    assert state["running"] is False
    # A failed proxy reload cannot guarantee the live proxy changed; the
    # recovery status is explicitly degraded rather than falsely successful.
    if failure == "reload_proxy":
        assert result.state == "rollback_failed"
    else:
        assert result.state == "rolled_back"


def test_adapter_refuses_registry_without_public_base_url(tmp_path):
    plan, release, adapter, registry, unit, proxy, receipt, state, events = fixture(tmp_path)
    cfg = json.loads(registry.read_text())
    cfg.pop("public_base_url")
    registry.write_text(json.dumps(cfg))
    result = activate(plan, release, adapter)
    assert result.state == "rolled_back"
    assert not receipt.exists()


def test_adapter_failed_attestation_cleanup(tmp_path):
    plan, release, adapter, registry, unit, proxy, receipt, state, events = fixture(tmp_path)
    # Force a post-health failure while writing attestation.
    adapter.attestation_path = tmp_path / "missing" / "demo.sha"
    # Parent creation is intentionally permitted; simulate a race with a symlink.
    adapter.attestation_path.parent.symlink_to(tmp_path, target_is_directory=True)
    result = activate(plan, release, adapter)
    assert result.state in {"rolled_back", "rollback_failed"}
    assert not unit.exists()
    assert not receipt.exists()


def test_adapter_persists_recovery_snapshot_before_mutation(tmp_path):
    import uuid
    from onboarding_recovery import load_snapshot
    plan, release, adapter, registry, unit, proxy, receipt, state, events = fixture(tmp_path)
    root = tmp_path / "private-snapshots"
    adapter.snapshot_root = root
    transaction_id = str(uuid.uuid4())
    original = registry.read_bytes()
    result = execute_transaction(
        plan, release, adapter, transaction_id=transaction_id,
        explicitly_approved=True, production_enablement=True
    )
    assert result.state == "completed"
    stored = load_snapshot(root, transaction_id)
    assert stored["registry"] == original
    assert stored["unit"] is None
    assert stored["proxy"] is None


def test_unavailable_recovery_store_blocks_activation(tmp_path):
    import uuid
    plan, release, adapter, registry, unit, proxy, receipt, state, events = fixture(tmp_path)
    root = tmp_path / "exposed"
    root.mkdir()
    root.chmod(0o755)
    adapter.snapshot_root = root
    result = execute_transaction(
        plan, release, adapter, transaction_id=str(uuid.uuid4()),
        explicitly_approved=True, production_enablement=True
    )
    assert result.state == "rolled_back"
    assert not unit.exists()
    assert registry.read_text().find('"applications": []') >= 0
    assert state["running"] is False
