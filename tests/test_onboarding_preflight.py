"""Offline activation preflight and review-gate regression tests."""
from pathlib import Path
import pytest

from onboarding import OnboardingError
from onboarding_release import prepare_release
from onboarding_preflight import deployment_preflight, activation_checklist


def fixture_release(tmp_path):
    sha = "a" * 40
    root = tmp_path / "staging"
    root.mkdir()
    source = root / "demo-aaaaaaaaaaaa"
    source.mkdir()
    (source / "app.py").write_text("pass\n")
    releases = tmp_path / "releases"
    releases.mkdir()
    staged = {"application": "demo", "commit_sha": sha,
              "repository": "zageabb/demo", "staged_path": str(source)}
    release = prepare_release(staged, root, releases)
    plan = {"application": "demo", "commit_sha": sha,
            "stage_only": True, "requires_approval": True,
            "port": 5301, "service_unit": "uda-demo.service",
            "entrypoint_pending_approval": ["python", "app.py"],
            "required_environment": ["SECRET_KEY"], "proxy_path": "/apps/demo/"}
    env = tmp_path / "private.env"
    env.write_text("SECRET_KEY=placeholder\n")
    env.chmod(0o600)
    return release, plan, env


def run_preflight(release, plan, env, registry=None):
    return deployment_preflight(
        release, plan, registry or {"applications": []},
        environment_file=env,
        service_exists=lambda _: False,
        port_available=lambda _: True,
    )


def test_approved_preflight_never_authorises_execution(tmp_path):
    release, plan, env = fixture_release(tmp_path)
    result = run_preflight(release, plan, env)
    assert result["release_verified"] is True
    assert result["execution_allowed"] is False
    assert result["approval_required"] is True
    assert result["unit_preview"].startswith("# UDA installation PREVIEW ONLY")
    assert len(activation_checklist(result)) == 7


def test_unverified_release_rejected(tmp_path):
    release, plan, env = fixture_release(tmp_path)
    Path(release["release_path"]).joinpath("app.py").write_text("tampered")
    with pytest.raises(OnboardingError, match="checksum"):
        run_preflight(release, plan, env)


def test_port_reused_before_activation(tmp_path):
    release, plan, env = fixture_release(tmp_path)
    with pytest.raises(OnboardingError, match="port collision"):
        run_preflight(release, plan, env, {"applications": [{"port": 5301}]})


def test_unaudited_approval_rejected(tmp_path):
    release, plan, env = fixture_release(tmp_path)
    plan["requires_approval"] = False
    with pytest.raises(OnboardingError, match="administrator approval"):
        run_preflight(release, plan, env)


def test_untrusted_service_unit_rejected(tmp_path):
    release, plan, env = fixture_release(tmp_path)
    with pytest.raises(OnboardingError, match="service name"):
        deployment_preflight(
            release, plan, {"applications": []},
            environment_file=env,
            service_exists=lambda _: True,
            port_available=lambda _: True,
        )


def test_environment_mode_must_be_private(tmp_path):
    release, plan, env = fixture_release(tmp_path)
    env.chmod(0o644)
    with pytest.raises(OnboardingError, match="permissions"):
        run_preflight(release, plan, env)


def test_missing_environment_file_rejected(tmp_path):
    release, plan, env = fixture_release(tmp_path)
    env.unlink()
    with pytest.raises(OnboardingError, match="absent"):
        run_preflight(release, plan, env)


def test_release_approval_cannot_be_used_for_another_sha(tmp_path):
    release, plan, env = fixture_release(tmp_path)
    plan["commit_sha"] = "b" * 40
    with pytest.raises(OnboardingError, match="SHA differ"):
        run_preflight(release, plan, env)


def test_unknown_port_check_is_fail_closed(tmp_path):
    release, plan, env = fixture_release(tmp_path)
    with pytest.raises(OnboardingError, match="port is available"):
        deployment_preflight(release, plan, {"applications": []},
                             environment_file=env, service_exists=lambda _: False)
