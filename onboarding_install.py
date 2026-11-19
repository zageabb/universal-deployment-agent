"""Approval-gated, non-executing repository staging for UDA onboarding.

This module intentionally stops before build, systemd, registry or Caddy changes.
It is designed to be a safe precursor for a separately-reviewed install worker.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
from typing import Any

from onboarding import OnboardingError, inspect_repo, plan_registration, repository_name

SHA40 = re.compile(r"^[0-9a-f]{40}$")
MAX_TICKET_AGE = 15 * 60
PORT_START = 5200
PORT_END = 5999


def allocate_port(registry: dict, requested: int | str, start: int = PORT_START,
                  end: int = PORT_END, probe=None) -> int:
    """Preview-only assignment; caller must recheck under deployment lock."""
    used = {app.get("port") for app in registry.get("applications", [])
            if type(app.get("port")) is int}
    def is_free(port):
        if probe is not None:
            return bool(probe(port))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
            try:
                handle.bind(("127.0.0.1", port))
            except OSError:
                return False
            return True
    if requested != "auto":
        if type(requested) is not int or not 1024 <= requested <= 65535:
            raise OnboardingError("Port must be auto or a valid unprivileged port")
        if requested in used or not is_free(requested):
            raise OnboardingError("Port already allocated or bound")
        return requested
    for port in range(start, end + 1):
        if port not in used and is_free(port):
            return port
    raise OnboardingError("No available application ports")


def prepare_plan(preview: dict, registry: dict, probe=None) -> dict:
    plan = plan_registration(preview, registry)
    plan["port"] = allocate_port(registry, plan["port"], probe=probe)
    plan["requires_approval"] = True
    plan["stage_only"] = True
    return plan


def _canonical(plan: dict) -> bytes:
    return json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def issue_ticket(plan: dict, secret: bytes, now: int | None = None) -> str:
    """HMAC protects the complete plan from browser-side modification."""
    if len(secret) < 32:
        raise OnboardingError("Approval signing key is too short")
    stamp = int(time.time() if now is None else now)
    payload = dict(plan)
    payload["issued_at"] = stamp
    # Bound plan size and ensure it contains only serialisable data.
    data = _canonical(payload)
    if len(data) > 16_384:
        raise OnboardingError("Installation plan is too large")
    import base64
    encoded = base64.urlsafe_b64encode(data).decode().rstrip("=")
    digest = hmac.new(secret, data, hashlib.sha256).hexdigest()
    return f"{encoded}.{digest}"


def verify_ticket(ticket: str, secret: bytes, now: int | None = None) -> dict:
    import base64
    if not isinstance(ticket, str) or len(ticket) > 24_000 or ticket.count(".") != 1:
        raise OnboardingError("Invalid approval ticket")
    encoded, signature = ticket.split(".", 1)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", encoded) or not re.fullmatch(r"[a-f0-9]{64}", signature):
        raise OnboardingError("Invalid approval ticket")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        supplied = json.loads(raw)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise OnboardingError("Malformed approval ticket") from exc
    if not isinstance(supplied, dict) or _canonical(supplied) != raw:
        raise OnboardingError("Non-canonical approval ticket")
    expected = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise OnboardingError("Installation plan was modified")
    stamp = supplied.get("issued_at")
    now = int(time.time() if now is None else now)
    if type(stamp) is not int or stamp > now + 30 or now - stamp > MAX_TICKET_AGE:
        raise OnboardingError("Approval expired; inspect the repository again")
    if supplied.get("stage_only") is not True or supplied.get("requires_approval") is not True:
        raise OnboardingError("Ticket is not authorised for safe staging")
    if not isinstance(supplied.get("commit_sha"), str) or not SHA40.fullmatch(supplied["commit_sha"]):
        raise OnboardingError("Invalid pinned commit")
    return supplied


def stage_checkout(plan: dict, staging_root: Path, *, clone_run=None) -> dict:
    """Clone a pinned public commit into a new, isolated directory.

    Never runs code from repository, never modifies production UDA configuration.
    Caller must arrange OS-level isolation and separate git access credentials.
    """
    repository = plan.get("repository")
    if not isinstance(repository, str):
        raise OnboardingError("Missing repository")
    repository_name("https://github.com/" + repository)
    sha = plan.get("commit_sha")
    if not isinstance(sha, str) or not SHA40.fullmatch(sha):
        raise OnboardingError("Invalid source commit")
    name = plan.get("application")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", name):
        raise OnboardingError("Invalid application name")
    if staging_root.expanduser().is_symlink():
        raise OnboardingError("Staging root must not be a symlink")
    root = staging_root.expanduser().resolve(strict=True)
    if root.is_symlink():
        raise OnboardingError("Staging root must not be a symlink")
    target = root / f"{name}-{sha[:12]}"
    if target.exists() or target.is_symlink():
        raise OnboardingError("Staging destination already exists")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never",
           "GIT_LFS_SKIP_SMUDGE": "1", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull}
    runner = clone_run or subprocess.run
    def run(args, timeout):
        try:
            result = runner(args, text=True, capture_output=True, check=False,
                            timeout=timeout, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OnboardingError("Repository staging command failed") from exc
        if result.returncode:
            raise OnboardingError("Repository staging command failed")
        return result.stdout.strip()
    try:
        remote = f"https://github.com/{repository}.git"
        run(["git", "-c", "credential.helper=", "clone", "--no-checkout",
             "--depth", "1", "--branch", plan["branch"], "--", remote, str(target)], 120)
        actual = run(["git", "-C", str(target), "rev-parse", "HEAD"], 15)
        if actual != sha:
            raise OnboardingError("Branch moved since approval; obtain a new preview")
        run(["git", "-C", str(target), "-c", "core.hooksPath=/dev/null",
             "checkout", "--detach", sha], 45)
        # A symbolic link could escape the staged tree during later processing.
        for directory, dirs, files in os.walk(target, followlinks=False):
            for part in dirs + files:
                item = Path(directory) / part
                if item.is_symlink():
                    raise OnboardingError("Staged repository contains symlinks; manual review required")
        return {"repository": repository, "application": name, "commit_sha": sha,
                "staged_path": str(target), "status": "staged_only",
                "service_created": False, "registry_modified": False}
    except (OnboardingError, OSError, ValueError):
        if target.exists() and target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        raise


def approved_stage(ticket: str, secret: bytes, registry: dict, staging_root: Path,
                   *, now: int | None = None, inspector=inspect_repo, clone_run=None) -> dict:
    """Recheck all non-secret inputs; signed ticket authorises staging, not installation."""
    plan = verify_ticket(ticket, secret, now)
    preview = inspector("https://github.com/" + plan["repository"], plan["branch"])
    if preview["commit_sha"] != plan["commit_sha"]:
        raise OnboardingError("Repository changed after approval")
    fresh = prepare_plan(preview, registry)
    if any(fresh[k] != plan[k] for k in (
            "repository", "branch", "commit_sha", "application",
            "service_unit", "port", "proxy_path",
            "required_environment", "runtime", "health_path", "group",
            "runtime_version", "runtime_working_dir", "build_working_dir",
            "auto_update_requested", "github_reporting_requested",
            "build_commands_pending_approval", "entrypoint_pending_approval")):
        raise OnboardingError("Installation plan changed after approval")
    if os.environ.get("UDA_GITHUB_TOKEN") and clone_run is None:
        from onboarding_private import stage_private_snapshot
        return stage_private_snapshot(plan, staging_root, os.environ["UDA_GITHUB_TOKEN"])
    return stage_checkout(plan, staging_root, clone_run=clone_run)
