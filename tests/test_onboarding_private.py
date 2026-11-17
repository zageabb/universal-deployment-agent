"""Offline private repository source staging tests."""
import base64
import hashlib
from pathlib import Path

import pytest

from onboarding import OnboardingError
from onboarding_private import stage_private_snapshot


SHA = "a" * 40
TREE = "b" * 40


def blob(content: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\x00" + content).hexdigest()


def data(path="app.py", content=b"print('hello')\n", mode="100644"):
    return [{"type": "blob", "path": path, "size": len(content),
             "sha": blob(content), "mode": mode}]


def api_fixture(rows, content):
    def handler(repo, endpoint, token):
        assert repo == "zageabb/private"
        assert token == "mock-token"
        if endpoint == f"git/commits/{SHA}":
            return {"tree": {"sha": TREE}}
        if endpoint == f"git/trees/{TREE}?recursive=1":
            return {"truncated": False, "tree": rows}
        if endpoint == f"git/blobs/{blob(content)}":
            return {"encoding": "base64", "content": base64.b64encode(content).decode()}
        raise AssertionError(endpoint)
    return handler


def plan():
    return {"repository": "zageabb/private", "application": "demo", "commit_sha": SHA}


def test_private_snapshot_stages_pinned_sha_without_git(tmp_path):
    content = b"print('hello')\n"
    result = stage_private_snapshot(plan(), tmp_path, "mock-token",
                                    api=api_fixture(data(content=content), content))
    path = Path(result["staged_path"])
    assert path.joinpath("app.py").read_bytes() == content
    assert result["status"] == "staged_only"
    assert result["source"] == "github_api"
    assert result["registry_modified"] is False
    assert not list(path.glob(".git"))


@pytest.mark.parametrize("path", [
    "../escape", "/absolute", "folder/../file", "folder//file", ".git/config",
    "a\\b", "./file",
])
def test_invalid_snapshot_paths_rejected(tmp_path, path):
    content = b"code"
    with pytest.raises(OnboardingError, match="path"):
        stage_private_snapshot(plan(), tmp_path, "mock-token",
                               api=api_fixture(data(path, content), content))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("mode", ["120000", "160000"])
def test_links_and_submodules_rejected(tmp_path, mode):
    content = b"link"
    with pytest.raises(OnboardingError, match="Links and submodules"):
        stage_private_snapshot(plan(), tmp_path, "mock-token",
                               api=api_fixture(data(content=content, mode=mode), content))


def test_truncated_tree_rejected(tmp_path):
    def api(repo, endpoint, token):
        if "git/commits" in endpoint:
            return {"tree": {"sha": TREE}}
        return {"truncated": True, "tree": []}
    with pytest.raises(OnboardingError, match="Incomplete"):
        stage_private_snapshot(plan(), tmp_path, "mock-token", api=api)


def test_blob_digest_mismatch_removes_partial_directory(tmp_path):
    contents = b"valid content"
    rows = data(content=contents)
    def api(repo, endpoint, token):
        if "git/commits" in endpoint:
            return {"tree": {"sha": TREE}}
        if "git/trees" in endpoint:
            return {"truncated": False, "tree": rows}
        return {"encoding": "base64",
                "content": base64.b64encode(b"other content").decode()}
    with pytest.raises(OnboardingError, match="size mismatch|integrity mismatch"):
        stage_private_snapshot(plan(), tmp_path, "mock-token", api=api)
    assert not list(tmp_path.iterdir())


def test_reject_overlarge_manifest_without_fetching_blobs(tmp_path):
    rows = [{"type": "blob", "path": "big.bin", "size": 9 * 1024 * 1024,
             "sha": "d" * 40, "mode": "100644"}]
    def api(repo, endpoint, token):
        if "git/commits" in endpoint:
            return {"tree": {"sha": TREE}}
        if "git/trees" in endpoint:
            return {"truncated": False, "tree": rows}
        raise AssertionError("Blob must never be downloaded")
    with pytest.raises(OnboardingError, match="size"):
        stage_private_snapshot(plan(), tmp_path, "mock-token", api=api)


def test_token_required(tmp_path):
    with pytest.raises(OnboardingError, match="token"):
        stage_private_snapshot(plan(), tmp_path, "")


def test_stage_refuses_existing_release_directory(tmp_path):
    destination = tmp_path / f"demo-{SHA[:12]}"
    destination.mkdir()
    content = b"hello"
    with pytest.raises(OnboardingError, match="already exists"):
        stage_private_snapshot(plan(), tmp_path, "mock-token",
                               api=api_fixture(data(content=content), content))


def test_authenticated_routing_stages_private_without_git(tmp_path, monkeypatch):
    import onboarding_install as install
    monkeypatch.setenv("UDA_GITHUB_TOKEN", "mock-token")
    preview = {"repository": "zageabb/private", "branch": "main",
               "commit_sha": SHA, "manifest": {
                   "name": "demo", "port": 5300, "service_type": "systemd",
                   "runtime": "python", "health_path": "/health",
                   "auto_update_requested": False, "github_reporting_requested": False,
                   "proxy_enabled": False, "proxy_path": "/apps/demo/",
                   "required_environment": [],
                   "requested_build_commands": [], "requested_entrypoint": ["python", "app.py"]}}
    plan_value = install.prepare_plan(preview, {"applications": []}, probe=lambda _: True)
    ticket = install.issue_ticket(plan_value, b"k" * 32, now=1000)
    from unittest.mock import patch
    with patch("onboarding_private.stage_private_snapshot", return_value={"status": "staged_only"}) as stage, \
         patch.object(install, "prepare_plan", return_value=plan_value):
        result = install.approved_stage(
            ticket, b"k" * 32, {"applications": []}, tmp_path,
            now=1001, inspector=lambda *_: preview)
    assert result["status"] == "staged_only"
    stage.assert_called_once()
