"""V2-003 deterministic, *non-executing* user-systemd unit bundle renderer.

Only reviewed argv vectors can be represented. The bundle is a plan and has no
authority to write units or invoke systemctl. No host service adapter or public
activation path imports it.

Release file integrity and pinned source identity are reverified before
producing any unit text. The operator-supplied command allowlist is independent
of a repository manifest; the caller must establish that authority out of band.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from onboarding import OnboardingError
from onboarding_release import verify_prepared_release
from onboarding_v2_ubuntu_preflight import _unit
from uda_manifest_v2_validate import ManifestV2Error, validate as validate_v2

SHA = re.compile(r"^[0-9a-f]{40}$")
DANGEROUS = re.compile(r"[\x00-\x1f\x7f]")
MAX_UNIT_TEXT = 16 * 1024
MAX_ARG = 1024
APPROVED_INTERPRETERS = frozenset({
    "/usr/bin/python3", "/usr/bin/node", "/usr/bin/uvicorn",
})


def _quote(arg: str) -> str:
    """Escape for systemd unit values, not a shell command string."""
    if (not isinstance(arg, str) or not arg or len(arg) > MAX_ARG or
            DANGEROUS.search(arg)):
        raise OnboardingError("Unsafe systemd argv value")
    # systemd expands % specifiers, including within quotes.
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def _safe_root(path: Path, *, label: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        raise OnboardingError(f"{label} must be an absolute real path")
    try:
        target = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise OnboardingError(f"{label} does not exist") from exc
    if not target.is_dir():
        raise OnboardingError(f"{label} must be a directory")
    return target


def _relative_dir(base: Path, relative: str) -> Path:
    if (not isinstance(relative, str) or relative.startswith("/") or
            any(part in (".", "..", "") for part in relative.split("/"))
            and relative != "."):
        raise OnboardingError("Unsafe service working directory")
    working = base if relative == "." else base / relative
    if working.is_symlink():
        raise OnboardingError("Service working directory cannot be a symlink")
    try:
        resolved = working.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise OnboardingError("Service working directory absent from verified release") from exc
    if not resolved.is_dir() or not resolved.is_relative_to(base):
        raise OnboardingError("Service working directory must remain in release")
    return resolved


def _env_file(value: Path) -> Path:
    if not isinstance(value, Path) or not value.is_absolute() or value.is_symlink():
        raise OnboardingError("Environment file must be absolute and unlinked")
    if (not value.is_file() or value.stat().st_mode & 0o077 or
            value.stat().st_nlink != 1):
        raise OnboardingError("Environment file must be private and unique")
    return value


def render_reviewed_units(
    manifest: dict, *, release_path: Path, source_commit_sha: str,
    environment_files: dict[str, Path],
    approved_entrypoints: dict[str, tuple[str, ...]],
    expected_units: dict[str, str],
) -> dict:
    """Return immutable review artifact, never write service files.

    Exact command matching is required; a manifest cannot grant its own
    trust. A production adapter would need to revalidate the bundle digest,
    source SHA, external operator approval and every host policy separately.
    """
    try:
        plan = validate_v2(manifest)
    except (ManifestV2Error, KeyError, TypeError) as exc:
        raise OnboardingError("Invalid V2 unit bundle manifest") from exc
    if (manifest["deployment"]["strategy"] != "systemd" or
            manifest["application"]["kind"] in ("platform", "library") or
            manifest.get("containers") or manifest.get("databases") or
            manifest.get("capabilities") or manifest.get("proxy", {}).get("routes")):
        raise OnboardingError("Advanced V2 deployment requires separate reviewed worker")
    services = {service["name"]: service for service in manifest.get("services", [])}
    if (not services or len(services) > 20 or
            set(services) != set(environment_files) or
            set(services) != set(approved_entrypoints) or
            set(services) != set(expected_units)):
        raise OnboardingError("Reviewed service, environment and unit identities differ")
    if (not isinstance(source_commit_sha, str) or not SHA.fullmatch(source_commit_sha)):
        raise OnboardingError("Pinned source commit required")
    root = _safe_root(release_path, label="Prepared release")
    receipt = verify_prepared_release(root, source_commit_sha)
    if receipt["application"] != manifest["application"]["name"]:
        raise OnboardingError("Prepared release belongs to another application")
    names = set()
    unit_texts = {}
    for name in plan["deployment_order"]:
        service = services[name]
        unit = _unit(expected_units[name])
        if unit in names or service.get("systemd_unit") != unit:
            raise OnboardingError("Systemd unit identity differs from reviewed manifest")
        names.add(unit)
        entry = service["entrypoint"]
        approved = approved_entrypoints[name]
        if (not isinstance(approved, tuple) or
                tuple(entry) != approved or not approved or
                not all(isinstance(arg, str) for arg in approved)):
            raise OnboardingError("Service entrypoint differs from independently reviewed argv")
        # No shell, env indirection, relative executable resolution or arbitrary
        # repo-supplied absolute executables. This is intentionally restrictive.
        if approved[0] not in APPROVED_INTERPRETERS:
            raise OnboardingError("Systemd executable is not on restricted runtime allowlist")
        working = _relative_dir(root, service.get("working_dir", "."))
        environment = _env_file(environment_files[name])
        dependencies = [expected_units[dep] for dep in service.get("depends_on", [])]
        dependencies = [_unit(dep) for dep in dependencies]
        restart = service.get("restart", "on-failure")
        if restart not in ("on-failure", "always", "never"):
            raise OnboardingError("Unsupported restricted service restart policy")
        text = "\n".join([
            "# UDA V2 REVIEW ARTIFACT ONLY — NOT INSTALLED",
            "[Unit]",
            f"Description=UDA {manifest['application']['name']} / {name}",
            "After=" + " ".join(sorted(dependencies)) if dependencies else "After=basic.target",
            * (["Requires=" + " ".join(sorted(dependencies))] if dependencies else []),
            "",
            "[Service]", "Type=simple",
            f"WorkingDirectory={_quote(str(working))}",
            f"EnvironmentFile={_quote(str(environment))}",
            "ExecStart=" + " ".join(_quote(arg) for arg in approved),
            "Restart=" + ("no" if restart == "never" else restart),
            "NoNewPrivileges=yes", "PrivateTmp=yes",
            "ProtectSystem=strict", "ProtectHome=read-only",
            "RestrictSUIDSGID=yes", "LockPersonality=yes",
            "CapabilityBoundingSet=", "AmbientCapabilities=",
            "UMask=0077", "",
            "[Install]", "WantedBy=default.target", "",
        ])
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_UNIT_TEXT:
            raise OnboardingError("Rendered unit exceeds output bound")
        unit_texts[unit] = text
    hashes = {unit: hashlib.sha256(text.encode("utf-8")).hexdigest()
              for unit, text in sorted(unit_texts.items())}
    evidence = {
        "application": manifest["application"]["name"],
        "commit_sha": source_commit_sha,
        "order": [expected_units[name] for name in plan["deployment_order"]],
        "unit_hashes": hashes,
    }
    digest = hashlib.sha256(json.dumps(
        evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        **evidence,
        "bundle_sha256": digest,
        "units": unit_texts,
        "approval_required": True,
        "deployment_allowed": False,
        "status": "review_only",
    }
