"""Regression tests for opt-in deployment reporting (no network required)."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, Mock
import pytest

import deployment_reporting as reporting


def init_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "README.md").write_text("UDA test")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                    "https://github.com/zageabb/demo.git"], check=True)
    sha = reporting.git(repo, "rev-parse", "HEAD")
    return repo, sha


@pytest.mark.parametrize("origin,expected", [
    ("https://github.com/zageabb/demo.git", "zageabb/demo"),
    ("git@github.com:zageabb/demo.git", "zageabb/demo"),
    ("ssh://git@github.com/zageabb/demo.git", "zageabb/demo"),
    ("https://evil.example/zageabb/demo.git", None),
    ("https://github.com.evil.example/zageabb/demo.git", None),
    ("file:///tmp/demo", None),
])
def test_github_origin_allowlist(origin, expected):
    assert reporting.github_repository(origin) == expected


def test_unattested_checkout_does_not_claim_running_version(tmp_path):
    repo, sha = init_repo(tmp_path)
    item = reporting.inventory_item({"name": "demo", "repo_path": str(repo), "branch": "main"})
    assert item["checkout_sha"] == sha
    assert item["running_sha"] is None
    assert item["state"] == "unverified"


def test_clean_attested_checkout(tmp_path):
    repo, sha = init_repo(tmp_path)
    attestation = tmp_path / "running.sha"
    attestation.write_text(sha + "\n")
    item = reporting.inventory_item({"name": "demo", "repo_path": str(repo),
                                     "branch": "main", "deployed_sha_file": str(attestation)})
    assert item["state"] == "matched"
    assert item["running_sha"] == sha
    assert item["repository"] == "zageabb/demo"


def test_dirty_checkout_never_publishable(tmp_path):
    repo, sha = init_repo(tmp_path)
    (repo / "README.md").write_text("local uncommitted change")
    attestation = tmp_path / "running.sha"
    attestation.write_text(sha)
    item = reporting.inventory_item({"name": "demo", "repo_path": str(repo),
                                     "deployed_sha_file": str(attestation)})
    assert item["state"] == "dirty"
    with pytest.raises(ValueError, match="Refusing"):
        reporting.publish_deployment(item, "fake-token")


def test_attestation_mismatch_never_publishable(tmp_path):
    repo, sha = init_repo(tmp_path)
    attestation = tmp_path / "running.sha"
    attestation.write_text("a" * 40)
    item = reporting.inventory_item({"name": "demo", "repo_path": str(repo),
                                     "deployed_sha_file": str(attestation)})
    assert item["state"] == "mismatch"
    with pytest.raises(ValueError):
        reporting.publish_deployment(item, "fake-token")


def test_service_only_application_is_not_inspected():
    assert reporting.inventory_item({"name": "legacy", "deployment_enabled": False})["state"] == "service_only"


def test_publisher_sends_verified_ref_to_github_only():
    item = {"repository": "zageabb/demo", "running_sha": "a" * 40, "state": "matched",
            "environment": "production"}
    first = Mock()
    first.__enter__ = Mock(return_value=first)
    first.__exit__ = Mock(return_value=None)
    second = Mock()
    second.__enter__ = Mock(return_value=second)
    second.__exit__ = Mock(return_value=None)
    with patch.object(reporting, "urlopen", side_effect=[first, second]) as send, \
         patch.object(reporting.json, "load", side_effect=[{"id": 123}, {"id": 456}]):
        result = reporting.publish_deployment(item, "fake-token", "https://example.com/app")
    assert result["deployment_id"] == 123
    assert send.call_count == 2
    create, update = [call.args[0] for call in send.call_args_list]
    assert create.full_url == "https://api.github.com/repos/zageabb/demo/deployments"
    assert json.loads(create.data)["ref"] == "a" * 40
    assert json.loads(update.data)["state"] == "success"


def test_unknown_repository_and_missing_token_are_rejected():
    item = {"repository": None, "running_sha": "a" * 40, "state": "matched"}
    with pytest.raises(ValueError):
        reporting.publish_deployment(item, "fake")
    item["repository"] = "zageabb/demo"
    with pytest.raises(ValueError):
        reporting.publish_deployment(item, "")


def test_atomic_attestation_is_created_outside_repository(tmp_path):
    repo, sha = init_repo(tmp_path)
    marker = tmp_path / "private" / "running.sha"
    reporting.write_attestation({"repo_path": str(repo), "deployed_sha_file": str(marker)}, sha)
    assert marker.read_text() == sha + "\n"
    assert marker.stat().st_mode & 0o777 == 0o600


def test_attestation_cannot_be_written_into_checkout(tmp_path):
    repo, sha = init_repo(tmp_path)
    with pytest.raises(ValueError, match="outside the repository"):
        reporting.write_attestation({"repo_path": str(repo),
                                     "deployed_sha_file": str(repo / "running.sha")}, sha)


def test_auto_deployer_attests_only_after_health(tmp_path, monkeypatch):
    import deploy_agent
    repo, sha = init_repo(tmp_path)
    marker = tmp_path / "private" / "running.sha"
    app = {"name": "demo", "enabled": True, "auto_deploy": True,
           "repo_path": str(repo), "branch": "main",
           "restart_command": ["true"], "health_url": "http://127.0.0.1:9999/health",
           "deployed_sha_file": str(marker)}
    remote = "a" * 40
    monkeypatch.setattr(deploy_agent, "inspect_application", lambda *_: {
        "repo": repo, "dirty": "", "local": sha, "remote": remote, "update_available": True})
    monkeypatch.setattr(deploy_agent, "git", lambda *_: "")
    monkeypatch.setattr(deploy_agent, "run", lambda *_ , **kw: "")
    monkeypatch.setattr(deploy_agent, "diagnostics", lambda *_: {})
    observed = []
    monkeypatch.setattr(deploy_agent, "health_check", lambda *_: observed.append("healthy"))
    result = deploy_agent.deploy_application(app, False, deploy_agent.logging.getLogger("test"))
    assert result["status"] == "deployed"
    assert observed == ["healthy"]
    assert marker.read_text().strip() == remote


def test_failed_health_never_attests_new_sha(tmp_path, monkeypatch):
    import deploy_agent
    repo, sha = init_repo(tmp_path)
    marker = tmp_path / "private" / "running.sha"
    app = {"name": "demo", "enabled": True, "auto_deploy": True,
           "repo_path": str(repo), "branch": "main",
           "restart_command": ["true"], "health_url": "http://127.0.0.1:9999/health",
           "deployed_sha_file": str(marker), "rollback": False}
    monkeypatch.setattr(deploy_agent, "inspect_application", lambda *_: {
        "repo": repo, "dirty": "", "local": sha, "remote": "a" * 40, "update_available": True})
    monkeypatch.setattr(deploy_agent, "git", lambda *_: "")
    monkeypatch.setattr(deploy_agent, "run", lambda *_ , **kw: "")
    monkeypatch.setattr(deploy_agent, "health_check",
                        lambda *_: (_ for _ in ()).throw(deploy_agent.DeployError("unhealthy")))
    with pytest.raises(deploy_agent.DeployError, match="unhealthy"):
        deploy_agent.deploy_application(app, False, deploy_agent.logging.getLogger("test"))
    assert not marker.exists()
