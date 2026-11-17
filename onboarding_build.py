"""Rootless, network-disabled container build workflow for approved UDA releases.

This worker is NOT wired to the dashboard and cannot activate or publish an
application. It requires an explicitly installed rootless Podman runtime and a
fixed administrator-configured image digest. Executing untrusted code remains
a security-sensitive opt-in operation and requires isolated-worker review.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

from onboarding import OnboardingError
from onboarding_release import verify_prepared_release

IMAGE = re.compile(r"^[a-zA-Z0-9._/:@-]+@sha256:[0-9a-f]{64}$")
MAX_COMMANDS = 20


def validate_commands(commands: list) -> list[list[str]]:
    if not isinstance(commands, list) or len(commands) > MAX_COMMANDS:
        raise OnboardingError("Unexpected build command list")
    for command in commands:
        if not isinstance(command, list) or not 1 <= len(command) <= 30:
            raise OnboardingError("Build commands must be argument arrays")
        for arg in command:
            if not isinstance(arg, str) or not arg or len(arg) > 1024 or any(ch in arg for ch in "\x00\r\n"):
                raise OnboardingError("Invalid build argument")
    return commands


def build_command(release: dict, commands: list, image: str,
                  output_dir: Path, *, runtime: str = "podman") -> list[list[str]]:
    """Generate a sandboxed build plan, not a shell script or automatic execution."""
    if release.get("status") != "prepared_inactive":
        raise OnboardingError("Build only from inactive release")
    source = Path(release["release_path"]).resolve(strict=True)
    verify_prepared_release(source, release["commit_sha"])
    if not isinstance(image, str) or not IMAGE.fullmatch(image):
        raise OnboardingError("Builder image must be pinned to a sha256 digest")
    if runtime != "podman":
        raise OnboardingError("Only rootless Podman is supported")
    if output_dir.expanduser().is_symlink():
        raise OnboardingError("Build output cannot be a symlink")
    output = output_dir.expanduser().resolve(strict=True)
    if not output.is_dir() or output.is_relative_to(source) or source.is_relative_to(output):
        raise OnboardingError("Build output must be separate from release source")
    validated = validate_commands(commands)
    if not validated:
        raise OnboardingError("No approved commands")
    base = [
        "podman", "run", "--rm", "--network=none", "--pull=never",
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=128", "--memory=1024m", "--cpus=2",
        "--user=65534:65534", "--userns=keep-id",
        "--tmpfs=/tmp:rw,nosuid,nodev,size=64m",
        "--volume", f"{source}:/workspace:ro",
        "--volume", f"{output}:/output:rw",
        "--workdir", "/workspace",
    ]
    return [base + [image] + cmd for cmd in validated]


def run_sandboxed_build(release: dict, commands: list, image: str, output_dir: Path,
                        *, approved: bool = False, runner=None) -> dict:
    """Explicit opt-in. No root operation, no host shell and no network.

    Result is a build artifact directory, not a deployed or accepted application.
    """
    if approved is not True:
        raise OnboardingError("Build requires separate operator approval")
    if os.geteuid() == 0:
        raise OnboardingError("Refusing to build as root")
    if shutil.which("podman") is None:
        raise OnboardingError("Rootless Podman is not installed")
    tasks = build_command(release, commands, image, output_dir)
    # Verify configured rootless mode rather than relying on command spelling.
    exec_run = runner or subprocess.run
    try:
        info = exec_run(["podman", "info", "--format", "{{.Host.Security.Rootless}}"],
                        text=True, capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OnboardingError("Rootless Podman preflight unavailable") from exc
    if info.returncode or info.stdout.strip().lower() != "true":
        raise OnboardingError("Podman runtime is not rootless")
    results = []
    for args in tasks:
        try:
            proc = exec_run(args, text=True, capture_output=True, timeout=600, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OnboardingError("Sandboxed build timed out or failed") from exc
        results.append({"returncode": proc.returncode,
                        "stdout_tail": proc.stdout[-4000:],
                        "stderr_tail": proc.stderr[-4000:]})
        if proc.returncode:
            raise OnboardingError(f"Sandboxed build failed: step {len(results)}")
    return {"status": "built_unactivated", "application": release["application"],
            "commit_sha": release["commit_sha"], "steps": len(results),
            "output_dir": str(output_dir.expanduser().resolve()), "results": results,
            "registry_modified": False, "service_started": False}
