"""V2-003 disposable Ubuntu systemd parser acceptance (non-activating).

Review-only unit bundles are checked by the *actual* systemd-analyze parser,
but only from an isolated private temporary directory. No systemctl, sudo,
unit installation, service start, network, Docker, or UDA registry access.

This is a syntax/preflight gate, not a service deployment adapter. The caller
must still obtain an independent approval and run real service acceptance on
an isolated Ubuntu test host before any production activation.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Callable

from onboarding import OnboardingError
from onboarding_v2_approval import _digest_bundle
from onboarding_v2_unit_sandbox import _atomic, _private_sandbox
from onboarding_v2_ubuntu_preflight import _unit

MAX_UNITS = 20
MAX_UNIT_SIZE = 16 * 1024
MAX_TOOL_OUTPUT = 64 * 1024
VERIFY_TOOL = "/usr/bin/systemd-analyze"


def _runner(argv: list[str], *, cwd: Path) -> tuple[int, str]:
    """Exact executable and command. No shell, PATH lookup, or source scripts."""
    if (len(argv) < 3 or len(argv) > MAX_UNITS + 2 or
            argv[:2] != [VERIFY_TOOL, "verify"] or
            any(not isinstance(path, str) or not path.endswith(".service")
                for path in argv[2:])):
        raise OnboardingError("Only systemd-analyze verify is permitted")
    if not Path(VERIFY_TOOL).is_file():
        raise OnboardingError("Ubuntu systemd-analyze is unavailable")
    try:
        result = subprocess.run(
            argv, cwd=cwd, shell=False, capture_output=True, text=True,
            timeout=15, check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "SYSTEMD_COLORS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise OnboardingError("systemd syntax validation could not complete") from exc
    output = result.stdout + result.stderr
    if len(output.encode("utf-8")) > MAX_TOOL_OUTPUT:
        raise OnboardingError("systemd verification output too large")
    return result.returncode, output


def verify_disposable_unit_bundle(
    bundle: dict, *, workspace: Path,
    run: Callable[..., tuple[int, str]] | None = None,
) -> dict:
    """Write isolated temporary unit copies and invoke systemd parser only.

    Return bounded evidence (status, names and hashes, diagnostic count), not
    source-authored commands or environment paths. Writes remain *only* in
    the caller-provided private temporary workspace under the OS temp root.
    """
    root = _private_sandbox(workspace)
    _digest_bundle(bundle)  # Re-hash texts, order and runtime evidence.
    if (bundle.get("approval_required") is not True or
            bundle.get("deployment_allowed") is not False):
        raise OnboardingError("Bundle must remain review-only")
    order = bundle["order"]
    if not 1 <= len(order) <= MAX_UNITS:
        raise OnboardingError("Unsafe systemd review unit count")
    unit_texts = bundle["units"]
    names = [_unit(unit) for unit in order]
    if len(set(names)) != len(names) or set(names) != set(unit_texts):
        raise OnboardingError("Unit inventory differs from reviewed bundle")
    destination = root / "systemd-verify"
    if destination.exists() or destination.is_symlink():
        raise OnboardingError("Disposable verification directory already exists")
    destination.mkdir(mode=0o700)
    if destination.stat().st_mode & 0o077:
        raise OnboardingError("Disposable verification directory is not private")
    files = []
    for unit in names:
        content = unit_texts[unit].encode("utf-8")
        if len(content) > MAX_UNIT_SIZE or b"\x00" in content:
            raise OnboardingError("Invalid reviewed unit text")
        target = destination / unit
        _atomic(target, content)
        files.append(target)
    # Verify only after all reviewed units are laid out together, preserving
    # After=/Requires= references between companion services.
    argv = [VERIFY_TOOL, "verify", *[str(path) for path in files]]
    verifier = run or _runner
    result = verifier(argv, cwd=destination)
    if (not isinstance(result, tuple) or len(result) != 2 or
            type(result[0]) is not int or not isinstance(result[1], str)):
        raise OnboardingError("Invalid systemd verifier response")
    exit_code, output = result
    if len(output.encode("utf-8")) > MAX_TOOL_OUTPUT:
        raise OnboardingError("Systemd verification output too large")
    return {
        "application": bundle["application"],
        "source_commit": bundle["commit_sha"],
        "bundle_sha256": bundle["bundle_sha256"],
        "verified_units": names,
        "unit_hashes": dict(bundle["unit_hashes"]),
        "syntax_verified": exit_code == 0,
        "diagnostic_lines": len(output.splitlines()),
        "requires_ubuntu_service_acceptance": True,
        "production_activation_allowed": False,
        "executed_unit_commands": 0,
        "systemd_command": "verify",
    }
