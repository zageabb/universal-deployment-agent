"""Repository onboarding unit tests: all tests work offline."""
from copy import deepcopy
from unittest.mock import patch, Mock

import pytest

import onboarding


def manifest():
    return {
        "schema_version": 1,
        "application": {"name": "demo-app", "display_name": "Demo App"},
        "runtime": {"type": "python"},
        "service": {
            "type": "systemd",
            "entrypoint": ["python", "app.py"],
            "port": "auto",
            "health_path": "/health",
        },
        "proxy": {"enabled": True, "path": "/apps/demo-app/", "authentication": "uda"},
        "build": {"commands": [["python", "-m", "compileall", "."]]},
        "environment": {"required": ["DATABASE_URL"]},
        "deployment": {"auto_update": True, "rollback": True},
    }


def test_valid_manifest_parses_and_commands_are_preview_only():
    import yaml
    result = onboarding.parse_manifest(yaml.safe_dump(manifest()).encode())
    assert result["name"] == "demo-app"
    assert result["runtime"] == "python"
    assert result["requested_build_commands"] == [["python", "-m", "compileall", "."]]
    assert result["required_environment"] == ["DATABASE_URL"]


@pytest.mark.parametrize("url", [
    "http://github.com/user/repo",
    "https://evil.example/user/repo",
    "https://github.com.evil.example/user/repo",
    "https://github.com/user/repo?token=secret",
    "https://user:pass@github.com/user/repo",
    "file:///var/tmp/a",
    "https://github.com/user/repo/issues",
])
def test_reject_unsafe_repository_urls(url):
    with pytest.raises(onboarding.OnboardingError):
        onboarding.repository_name(url)


def test_accept_github_repo():
    assert onboarding.repository_name("https://github.com/zageabb/demo.git") == "zageabb/demo"


@pytest.mark.parametrize("branch", [
    "../main", "main..bad", "/main", "feature//bad", "feature/.hidden",
    "ref@{0}", "feature ", "abc.lock",
])
def test_invalid_branches_rejected(branch):
    with pytest.raises(onboarding.OnboardingError):
        onboarding.validate_branch(branch)


def test_yaml_tags_do_not_execute():
    with pytest.raises(onboarding.OnboardingError):
        onboarding.parse_manifest(b"!!python/object/apply:os.system ['touch /tmp/evil']")


def test_manifest_size_limit():
    with pytest.raises(onboarding.OnboardingError, match="32 KiB"):
        onboarding.parse_manifest(b" " * (onboarding.MAX_MANIFEST_BYTES + 1))


@pytest.mark.parametrize("change", [
    lambda d: d.update(schema_version=2),
    lambda d: d["application"].update(name="../evil"),
    lambda d: d["runtime"].update(type="root-shell"),
    lambda d: d["service"].update(port=80),
    lambda d: d["service"].update(port=True),
    lambda d: d["proxy"].update(authentication="none"),
    lambda d: d["proxy"].update(path="/admin/"),
    lambda d: d["environment"].update(required=["DATABASE_URL", "BAD=VAL"]),
    lambda d: d["build"].update(commands=["rm -rf /"]),
    lambda d: d.update(untrusted_section={"hello": "world"}),
])
def test_reject_invalid_configuration(change):
    value = manifest()
    change(value)
    with pytest.raises(onboarding.OnboardingError):
        onboarding.validate_manifest(value)


def test_no_duplicate_applications_allowed():
    preview = {"repository": "zageabb/demo", "branch": "main",
               "commit_sha": "a" * 40,
               "manifest": onboarding.validate_manifest(manifest())}
    with pytest.raises(onboarding.OnboardingError, match="already registered"):
        onboarding.plan_registration(preview, {"applications": [{"name": "demo-app"}]})


def test_preview_plan_has_no_side_effects():
    preview = {"repository": "zageabb/demo", "branch": "main",
               "commit_sha": "a" * 40,
               "manifest": onboarding.validate_manifest(manifest())}
    result = onboarding.plan_registration(preview, {"applications": []})
    assert result["operation"] == "preview_only"
    assert result["registry_modified"] is False
    assert result["service_modified"] is False
    assert result["service_unit"] == "uda-demo-app.service"
    assert result["build_commands_pending_approval"]


def test_safe_clone_inspection_does_not_check_out_or_run_code():
    import subprocess
    head = "a" * 40
    calls = []
    def fake_run(args, **kwargs):
        calls.append(args)
        if args[0] == "git" and "clone" in args:
            return Mock(returncode=0, stdout=b"", stderr=b"")
        if args[-2:] == ["rev-parse", "HEAD"]:
            return Mock(returncode=0, stdout=head.encode(), stderr=b"")
        if args[-2:] == ["show", "HEAD:uda.yaml"]:
            import yaml
            return Mock(returncode=0, stdout=yaml.safe_dump(manifest()).encode(), stderr=b"")
        return Mock(returncode=1, stdout=b"", stderr=b"")
    with patch.object(onboarding.subprocess, "run", side_effect=fake_run):
        report = onboarding.inspect_repo("https://github.com/zageabb/demo", "main")
    assert report["commit_sha"] == head
    assert report["status"] == "preview_only"
    assert "--no-checkout" in calls[0]
    assert all("checkout" not in call for call in calls[1:])


def test_reject_manifest_missing_from_repo():
    def fake_run(args, **kwargs):
        if "clone" in args:
            return Mock(returncode=0, stdout=b"", stderr=b"")
        if args[-2:] == ["rev-parse", "HEAD"]:
            return Mock(returncode=0, stdout=b"a" * 40, stderr=b"")
        return Mock(returncode=1, stdout=b"", stderr=b"")
    with patch.object(onboarding.subprocess, "run", side_effect=fake_run):
        with pytest.raises(onboarding.OnboardingError, match="no root uda.yaml"):
            onboarding.inspect_repo("https://github.com/zageabb/demo")


def test_onboarding_routes_require_auth_and_csrf(tmp_path):
    import json
    import dashboard
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"applications": [], "dashboard_token": "secret"}))
    client = dashboard.create_app(config).test_client()
    assert client.get("/onboarding").status_code == 401
    assert client.post("/onboarding/preview").status_code == 401
    header = {"Authorization": "Basic YWRtaW46c2VjcmV0"}
    form = client.get("/onboarding", headers=header)
    assert form.status_code == 200
    assert b"Install from GitHub" in form.data
    assert client.post("/onboarding/preview", headers=header,
                       data={"repository_url": "https://github.com/owner/repo"}).status_code == 403


def test_onboarding_preview_does_not_mutate_registry(tmp_path):
    import json
    import dashboard
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"applications": [], "dashboard_token": "secret"}))
    client = dashboard.create_app(config).test_client()
    header = {"Authorization": "Basic YWRtaW46c2VjcmV0"}
    csrf = client.application.config["CSRF_TOKEN"]
    preview = {"repository": "owner/repo", "branch": "main",
               "commit_sha": "a" * 40, "manifest": onboarding.validate_manifest(manifest())}
    before = config.read_bytes()
    with patch.object(dashboard, "inspect_repo", return_value=preview) as inspect:
        response = client.post("/onboarding/preview", headers=header,
                               data={"csrf_token": csrf,
                                     "repository_url": "https://github.com/owner/repo",
                                     "branch": "main"})
    assert response.status_code == 200
    assert b"preview" in response.data.lower()
    assert config.read_bytes() == before
    inspect.assert_called_once()


def test_selected_branch_must_match_manifest_declared_branch():
    from unittest.mock import Mock
    import yaml
    value = manifest()
    value["source"] = {"branch": "develop"}
    def fake_run(args, **kwargs):
        if "clone" in args:
            return Mock(returncode=0, stdout=b"", stderr=b"")
        if args[-2:] == ["rev-parse", "HEAD"]:
            return Mock(returncode=0, stdout=b"a" * 40, stderr=b"")
        if args[-2:] == ["show", "HEAD:uda.yaml"]:
            return Mock(returncode=0, stdout=yaml.safe_dump(value).encode(), stderr=b"")
        return Mock(returncode=1, stdout=b"", stderr=b"")
    with patch.object(onboarding.subprocess, "run", side_effect=fake_run):
        with pytest.raises(onboarding.OnboardingError, match="source.branch"):
            onboarding.inspect_repo("https://github.com/zageabb/demo", "main")


def test_authenticated_private_repo_uses_pinned_sha_without_cloning(monkeypatch):
    import base64
    import json
    import yaml
    monkeypatch.setenv("UDA_GITHUB_TOKEN", "mock-token")
    sha = "b" * 40
    urls = []
    class FakeResponse:
        def __init__(self, body):
            self.body = body
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def read(self, limit=-1):
            return self.body
    def fake_urlopen(request, timeout=15):
        urls.append(request.full_url)
        if "/commits/" in request.full_url:
            return FakeResponse(json.dumps({"sha": sha}).encode())
        assert request.full_url.endswith("contents/uda.yaml?ref=" + sha)
        encoded = base64.b64encode(yaml.safe_dump(manifest()).encode()).decode()
        return FakeResponse(json.dumps({"encoding": "base64", "content": encoded}).encode())
    with patch.object(onboarding, "urlopen", side_effect=fake_urlopen), \
         patch.object(onboarding.subprocess, "run") as git:
        result = onboarding.inspect_repo("https://github.com/zageabb/private", "main")
    assert result["commit_sha"] == sha
    assert result["repository"] == "zageabb/private"
    assert len(urls) == 2
    git.assert_not_called()


def test_private_repo_bad_manifest_is_rejected(monkeypatch):
    import json
    monkeypatch.setenv("UDA_GITHUB_TOKEN", "mock-token")
    class FakeResponse:
        def __init__(self, value):
            self.value = value
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def read(self, *_):
            return json.dumps(self.value).encode()
    with patch.object(onboarding, "urlopen", side_effect=[
        FakeResponse({"sha": "b" * 40}),
        FakeResponse({"encoding": "base64", "content": "notbase64!!!"}),
    ]):
        with pytest.raises(onboarding.OnboardingError, match="invalid manifest"):
            onboarding.inspect_repo("https://github.com/zageabb/private")
