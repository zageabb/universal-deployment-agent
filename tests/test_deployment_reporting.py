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
