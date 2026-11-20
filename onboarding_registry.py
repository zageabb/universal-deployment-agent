"""Preview-only UDA registry entry and activation transaction blueprint.

An inactive candidate is not an installed app. This module never changes
production state and is safe to inspect before a future privileged installer.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from onboarding import OnboardingError


def inactive_registry_entry(plan: dict, release: dict) -> dict:
    """Generate a fail-closed UDA entry; it is NOT automatically saved."""
    if plan.get("application") != release.get("application"):
        raise OnboardingError("Registry plan differs from prepared release")
    if plan.get("commit_sha") != release.get("commit_sha"):
        raise OnboardingError("Registry source SHA differs from prepared release")
    if release.get("status") != "prepared_inactive":
        raise OnboardingError("Release is not in inactive state")
    name = plan["application"]
    unit = plan.get("service_unit")
    port = plan.get("port")
    if type(port) is not int or not 1024 <= port <= 65535:
        raise OnboardingError("Missing assigned port")
    path = plan.get("health_path")
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise OnboardingError("Invalid application health path")
    if not isinstance(unit, str) or unit != f"uda-{name}.service":
        raise OnboardingError("Only managed systemd apps are supported for this increment")
    entry = {
        "name": name,
        "display_name": name,
        "enabled": False,
        "auto_deploy": False,
        "deployment_enabled": False,
        "repo_path": release["release_path"],
        "branch": plan["branch"],
        "service_unit": unit,
        "restart_command": ["systemctl", "--user", "restart", "--", unit],
        "health_url": f"http://127.0.0.1:{port}{path}",
        "port": port,
        "proxy_enabled": False,
        "show_on_home": False,
        "rollback": True,
        "github_reporting_enabled": False,
        "onboarding_state": "pending_activation",
        "onboarding_commit_sha": plan["commit_sha"],
    }
    group = plan.get("group")
    if group is not None:
        if not isinstance(group, str) or not group.strip():
            raise OnboardingError("Invalid UDA group")
        entry["group"] = group
    return entry


def preview_registry_diff(plan: dict, release: dict, registry: dict) -> dict:
    candidate = inactive_registry_entry(plan, release)
    current = deepcopy(registry)
    if not isinstance(current.get("applications"), list):
        raise OnboardingError("UDA registry applications list is invalid")
    if any(item.get("name") == candidate["name"] for item in current["applications"]):
        raise OnboardingError("Application is already registered")
    if any(item.get("service_unit") == candidate["service_unit"]
           for item in current["applications"]):
        raise OnboardingError("Service unit already registered")
    if any(item.get("port") == candidate["port"] for item in current["applications"]):
        raise OnboardingError("Port already registered")
    current["applications"].append(candidate)
    return {
        "change": "add_disabled_candidate",
        "application": candidate["name"],
        "before_applications": len(registry["applications"]),
        "after_applications": len(current["applications"]),
        "candidate_entry": candidate,
        "proposed_registry": current,
        "registry_modified": False,
        "service_modified": False,
        "proxy_modified": False,
    }


def transaction_steps() -> list[dict]:
    """Deterministic future installer ordering and compensating actions."""
    return [
        {"step": "take_backup", "rollback": "retain_snapshot"},
        {"step": "verify_release", "rollback": "do_not_activate"},
        {"step": "verify_port_and_secrets", "rollback": "do_not_activate"},
        {"step": "build_as_unprivileged_user", "rollback": "discard_build"},
        {"step": "write_disabled_service", "rollback": "restore_previous_unit"},
        {"step": "start_loopback_and_health_check", "rollback": "stop_new_service"},
        {"step": "write_registry", "rollback": "restore_previous_registry"},
        {"step": "refresh_caddy", "rollback": "restore_previous_proxy_config"},
        {"step": "test_uda_auth", "rollback": "restore_previous_proxy_config"},
        {"step": "record_verified_sha", "rollback": "restore_previous_attestation"},
        {"step": "publish_github_deployment", "rollback": "record_delivery_failure"},
    ]
