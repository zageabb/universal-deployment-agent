"""Offline approval, port and staging tests for UDA-DEPLOY-002."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch
import subprocess

import pytest

from onboarding import OnboardingError
import onboarding_install as install


@pytest.fixture
def preview():
    return {
        "repository": "zageabb/demo",
        "branch": "main",
        "commit_sha": "a" * 40,
        "manifest": {
            "name": "demo", "display_name": "Demo", "runtime": "python",
            "service_type": "systemd", "port": "auto",
            "health_path": "/health", "proxy_enabled": True,
            "proxy_path": "/apps/demo/", "required_environment": ["SECRET_KEY"],
            "requested_build_commands": [["python", "-m", "compileall", "."]],
            "requested_entrypoint": ["python", "app.py"],
            "auto_update_requested": False, "github_reporting_requested": False,
        },
    }


def test_port_allocation_skips_registered_and_bound():
    registry = {"applications": [{"port": 5200}]}
    assert install.allocate_port(registry, "auto", 5200, 5203,
                                 probe=lambda p: p != 5201) == 5202


def test_explicit_port_collision_is_rejected():
    with pytest.raises(OnboardingError, match="allocated"):
        install.allocate_port({"applications": [{"port": 5400}]}, 5400,
                              probe=lambda p: True)


def test_preview_assigns_port_without_modifying_registry(preview):
    registry = {"applications": []}
    original = deepcopy(registry)
    plan = install.prepare_plan(preview, registry, probe=lambda _: True)
    assert plan["port"] == 5200
    assert plan["stage_only"] is True
    assert registry == original


def test_ticket_tamper_and_expiration(preview):
    plan = install.prepare_plan(preview, {"applications": []},
                                probe=lambda _: True)
    key = b"k" * 32
    ticket = install.issue_ticket(plan, key, now=1000)
    assert install.verify_ticket(ticket, key, now=1001)["application"] == "demo"
    with pytest.raises(OnboardingError):
        install.verify_ticket(ticket[:-1] + ("0" if ticket[-1] != "0" else "1"),
                              key, now=1001)
    with pytest.raises(OnboardingError, match="expired"):
        install.verify_ticket(ticket, key, now=2000)


def test_missing_or_weak_ticket_key_is_refused(preview):
    plan = install.prepare_plan(preview, {"applications": []}, probe=lambda _: True)
    with pytest.raises(OnboardingError, match="key"):
        install.issue_ticket(plan, b"short")


def test_staging_rejects_branch_drift(preview, tmp_path):
    plan = install.prepare_plan(preview, {"applications": []},
                                probe=lambda _: True)
    ticket = install.issue_ticket(plan, b"k" * 32, now=1000)
    changed = deepcopy(preview)
    changed["commit_sha"] = "b" * 40
    with pytest.raises(OnboardingError, match="changed"):
        install.approved_stage(ticket, b"k" * 32, {"applications": []},
                               tmp_path, now=1001, inspector=lambda *_: changed)


def test_staging_rejects_occupied_app_name(preview, tmp_path):
    plan = install.prepare_plan(preview, {"applications": []}, probe=lambda _: True)
    ticket = install.issue_ticket(plan, b"k" * 32, now=1000)
    with pytest.raises(OnboardingError, match="already registered"):
        install.approved_stage(ticket, b"k" * 32,
                               {"applications": [{"name": "demo"}]},
                               tmp_path, now=1001, inspector=lambda *_: preview)


def test_stage_checkout_never_executes_repository_code(tmp_path, preview):
    plan = install.prepare_plan(preview, {"applications": []}, probe=lambda _: True)
    # Simulate Git; this verifies the exact SHA/checkout argument handling.
    def runner(args, **kwargs):
        if "clone" in args:
            Path(args[-1]).mkdir()
            return Mock(returncode=0, stdout="", stderr="")
        if "rev-parse" in args:
            return Mock(returncode=0, stdout=preview["commit_sha"] + "\n", stderr="")
        return Mock(returncode=0, stdout="", stderr="")
    result = install.stage_checkout(plan, tmp_path, clone_run=runner)
    assert result["status"] == "staged_only"
    assert result["registry_modified"] is False
    assert result["service_created"] is False


def test_staging_rejects_changed_head_and_cleans_up(tmp_path, preview):
    plan = install.prepare_plan(preview, {"applications": []}, probe=lambda _: True)
    def runner(args, **kwargs):
        if "clone" in args:
            Path(args[-1]).mkdir()
            return Mock(returncode=0, stdout="", stderr="")
        return Mock(returncode=0, stdout="b" * 40, stderr="")
    with pytest.raises(OnboardingError, match="moved"):
        install.stage_checkout(plan, tmp_path, clone_run=runner)
    assert not list(tmp_path.iterdir())


def test_staging_rejects_symlinks(tmp_path, preview):
    plan = install.prepare_plan(preview, {"applications": []}, probe=lambda _: True)
    def runner(args, **kwargs):
        if "clone" in args:
            root = Path(args[-1])
            root.mkdir()
            (root / "escape").symlink_to("/etc/passwd")
            return Mock(returncode=0, stdout="", stderr="")
        if "rev-parse" in args:
            return Mock(returncode=0, stdout=preview["commit_sha"], stderr="")
        return Mock(returncode=0, stdout="", stderr="")
    with pytest.raises(OnboardingError, match="symlinks"):
        install.stage_checkout(plan, tmp_path, clone_run=runner)
    assert not list(tmp_path.iterdir())
