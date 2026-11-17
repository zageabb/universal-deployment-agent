"""Fail-closed activation preflight and audit plan.

This module only evaluates a prepared release. No service mutations, registry
edits, Caddy writes, command execution or database migrations occur here.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from onboarding import OnboardingError
from onboarding_release import verify_prepared_release, systemd_unit_preview


def deployment_preflight(
    release: dict, plan: dict, registry: dict, *,
    environment_file: Path | None = None,
    service_exists=None,
    port_available=None,
) -> dict:
    if plan.get("application") != release.get("application"):
        raise OnboardingError("Plan and prepared release application differ")
    if plan.get("commit_sha") != release.get("commit_sha"):
        raise OnboardingError("Plan and prepared release SHA differ")
    if plan.get("stage_only") is not True:
        raise OnboardingError("Cannot promote unreviewed onboarding plan")
    if plan.get("requires_approval") is not True:
        raise OnboardingError("Plan does not require administrator approval")
    if release.get("status") != "prepared_inactive":
        raise OnboardingError("Release is not in inactive preparation state")
    sha = plan["commit_sha"]
    prepared = verify_prepared_release(Path(release["release_path"]), sha)
    name = prepared["application"]
    if name in {app.get("name") for app in registry.get("applications", [])}:
        raise OnboardingError("Application was registered while release was prepared")
    unit = plan.get("service_unit")
    if unit:
        if unit in {app.get("service_unit") for app in registry.get("applications", [])}:
            raise OnboardingError("Systemd unit collision")
        if service_exists is None or service_exists(unit):
            raise OnboardingError("Cannot prove systemd service name is available")
    port = plan.get("port")
    if type(port) is not int or not (1024 <= port <= 65535):
        raise OnboardingError("Invalid allocated port")
    if port in {app.get("port") for app in registry.get("applications", [])}:
        raise OnboardingError("Configured port collision")
    if port_available is None or not port_available(port):
        raise OnboardingError("Cannot prove port is available at preflight")
    requirements = plan.get("required_environment", [])
    if not isinstance(requirements, list):
        raise OnboardingError("Invalid environment requirements")
    if requirements and environment_file is None:
        raise OnboardingError("Required environment file is not configured")
    unit_preview = None
    if unit:
        if environment_file is None:
            raise OnboardingError("Service requires protected environment file")
        if environment_file.is_symlink() or not environment_file.is_file():
            raise OnboardingError("Environment file is absent or symlinked")
        mode = environment_file.stat().st_mode & 0o777
        if mode & 0o077:
            raise OnboardingError("Environment file permissions are too broad")
        unit_preview = systemd_unit_preview(
            plan, Path(release["release_path"]), environment_file=environment_file)
    # This is a data-only preflight. It cannot itself authorize deployment.
    return {
        "application": name,
        "commit_sha": sha,
        "release_path": release["release_path"],
        "release_verified": True,
        "service_unit": unit,
        "unit_preview": unit_preview,
        "port": port,
        "proxy_path": plan.get("proxy_path"),
        "required_environment": requirements,
        "approval_required": True,
        "execution_allowed": False,
        "rollback_required": True,
        "state": "ready_for_external_review",
    }


def activation_checklist(preflight: dict) -> list[dict]:
    """Auditable sequence for the future privileged deployment worker."""
    if preflight.get("release_verified") is not True:
        raise OnboardingError("Unverified release")
    return [
        {"step": "record_previous_state", "mandatory": True,
         "detail": "Snapshot registry, existing units, proxy config, release pointer"},
        {"step": "install_restricted_runtime", "mandatory": True,
         "detail": "Use non-privileged build worker; allowlisted commands only"},
        {"step": "configure_service", "mandatory": True,
         "detail": "Generate unit from approved template and validate syntax"},
        {"step": "start_and_check", "mandatory": True,
         "detail": "Start on loopback, verify health and runtime commit"},
        {"step": "register_and_publish", "mandatory": True,
         "detail": "Atomically update UDA registry, reload Caddy, verify SSO"},
        {"step": "record_deployment", "mandatory": True,
         "detail": "Write SHA receipt only after health succeeds, then report to GitHub"},
        {"step": "rollback_on_any_failure", "mandatory": True,
         "detail": "Restore prior configuration and services, preserve audit"},
    ]
