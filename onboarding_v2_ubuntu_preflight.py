"""V2-003 restricted, READ-ONLY Ubuntu systemd evidence collector.

This is an inspection boundary, NOT a service activation adapter. Only two
allowlisted systemctl --user commands are permitted. The manifest never becomes
an argv element except for schema-checked service-unit identifiers preceded
by "--". No shell, sudo, registry writes or process management.
"""
from __future__ import annotations

from pathlib import Path
import os
import re
import subprocess
from typing import Callable, Sequence

from onboarding import OnboardingError
from uda_manifest_v2_validate import ManifestV2Error, validate as validate_v2

UNIT = re.compile(r"^[A-Za-z0-9_.@-]{1,180}\.service$")
MAX_UNITS = 256
MAX_OUTPUT = 128 * 1024
DETAIL_KEYS = ("Id", "LoadState", "ActiveState", "SubState", "FragmentPath", "WorkingDirectory")
SAFE_STATES = {"active", "inactive", "failed", "activating", "deactivating", "reloading", "maintenance"}


def _unit(value: str) -> str:
    if not isinstance(value, str) or not UNIT.fullmatch(value) or value.startswith("-") or ".." in value:
        raise OnboardingError("Unsafe systemd unit name")
    return value


def _default_run(argv: Sequence[str]) -> str:
    """Only two precise systemctl argv forms; no dashboard or YAML commands."""
    inventory = [
        "systemctl", "--user", "list-units", "--all", "--type=service",
        "--no-legend", "--plain", "--no-pager",
    ]
    inspect_prefix = [
        "systemctl", "--user", "show", "--no-pager",
        "--property=" + ",".join(DETAIL_KEYS), "--",
    ]
    if list(argv) != inventory and not (
            len(argv) == len(inspect_prefix) + 1 and
            list(argv[:-1]) == inspect_prefix and isinstance(argv[-1], str) and
            UNIT.fullmatch(argv[-1]) and not argv[-1].startswith("-") and
            ".." not in argv[-1]):
        raise OnboardingError("Only systemd read-only inspection is supported")
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    # User-systemd uses DBus / XDG session endpoints; preserve only these
    # trusted process environment names, never manifest-defined variables.
    for name in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        if os.environ.get(name):
            env[name] = os.environ[name]
    try:
        completed = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=8,
            check=False, env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OnboardingError("systemd inspection unavailable") from exc
    if completed.returncode:
        raise OnboardingError("systemd inspection failed")
    if len(completed.stdout.encode("utf-8")) > MAX_OUTPUT:
        raise OnboardingError("systemd inspection response exceeded size limit")
    return completed.stdout


class UserSystemdInspector:
    """Uses only read-only commands and redacts unit values from its summary."""

    def __init__(self, run: Callable[[Sequence[str]], str] | None = None):
        self.run = run or _default_run

    def _request(self, command: list[str]) -> str:
        if command[:2] != ["systemctl", "--user"]:
            raise OnboardingError("Invalid inspection command")
        output = self.run(command)
        if not isinstance(output, str) or len(output.encode("utf-8")) > MAX_OUTPUT:
            raise OnboardingError("Invalid systemd response")
        return output

    def inventory(self) -> list[str]:
        raw = self._request([
            "systemctl", "--user", "list-units", "--all", "--type=service",
            "--no-legend", "--plain", "--no-pager",
        ])
        result: list[str] = []
        for line in raw.splitlines():
            words = line.strip().lstrip("●").strip().split()
            if not words:
                continue
            if not UNIT.fullmatch(words[0]):
                raise OnboardingError("Unexpected systemd unit inventory format")
            result.append(_unit(words[0]))
        if len(result) > MAX_UNITS or len(result) != len(set(result)):
            raise OnboardingError("Systemd inventory is too large or ambiguous")
        return result

    def details(self, unit: str) -> dict:
        name = _unit(unit)
        data = self._request([
            "systemctl", "--user", "show", "--no-pager",
            "--property=" + ",".join(DETAIL_KEYS), "--", name,
        ])
        properties: dict[str, str] = {}
        for line in data.splitlines():
            if not line:
                continue
            if "=" not in line:
                raise OnboardingError("Malformed systemd evidence")
            key, value = line.split("=", 1)
            if key not in DETAIL_KEYS or key in properties:
                raise OnboardingError("Unexpected systemd evidence field")
            properties[key] = value
        if properties.get("Id") != name:
            raise OnboardingError("Systemd unit identity mismatch")
        if properties.get("ActiveState") not in SAFE_STATES:
            raise OnboardingError("Unknown systemd state")
        if properties.get("LoadState") not in ("loaded", "not-found", "masked", "error"):
            raise OnboardingError("Unknown systemd load state")
        return properties


def _located_within(value: str, checkout: Path) -> bool:
    if not value or not value.startswith("/"):
        return False
    path = Path(value)
    # Filesystem inspection is read-only and refuses symlinked source paths.
    if path.is_symlink():
        return False
    try:
        return path.resolve(strict=False).is_relative_to(checkout.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return False


def inspect_live_graph(
    manifest: dict, checkout: Path, inspector: UserSystemdInspector,
) -> dict:
    """Reconcile declared unit names with live user services, never mutate host.

    checkout is a trusted operator-provided path, not derived from manifest
    YAML. Discovery of undeclared companion units is conservative: a unit is
    associated only when its systemd WorkingDirectory is under checkout.
    Host wrapper units with a different WorkingDirectory remain an unresolved
    inventory question, not proof of absence.
    """
    try:
        validate_v2(manifest)
    except (ManifestV2Error, KeyError, TypeError) as exc:
        raise OnboardingError("Invalid v2 service graph") from exc
    if manifest["deployment"]["strategy"] != "systemd" or manifest.get("containers"):
        raise OnboardingError("Read-only unit reconciliation requires a systemd-only deployment")
    if not isinstance(checkout, Path) or not checkout.is_absolute() or checkout.is_symlink():
        raise OnboardingError("Checkout must be a trusted absolute directory")
    if not checkout.exists() or not checkout.is_dir():
        raise OnboardingError("Checkout does not exist")
    services = manifest.get("services", [])
    declared = {}
    for item in services:
        unit = item.get("systemd_unit")
        if not unit:
            raise OnboardingError("Every service must declare its exact systemd_unit for reconciliation")
        unit = _unit(unit)
        if unit in declared:
            raise OnboardingError("Duplicate service unit")
        declared[unit] = item["name"]
    installed = inspector.inventory()
    evidence = {unit: inspector.details(unit) for unit in installed}
    associated = {
        unit for unit, props in evidence.items()
        if _located_within(props.get("WorkingDirectory", ""), checkout)
    }
    missing = sorted(set(declared) - set(installed))
    undeclared = sorted(associated - set(declared))
    known = []
    for unit, service in sorted(declared.items()):
        props = evidence.get(unit)
        known.append({
            "service": service, "unit": unit,
            "load_state": props.get("LoadState", "not-found") if props else "not-found",
            "active_state": props.get("ActiveState", "unknown") if props else "unknown",
            "source_workdir_matches": bool(props and _located_within(props.get("WorkingDirectory", ""), checkout)),
        })
    owned = manifest.get("lifecycle", {}).get("owned_units", [])
    conflicts = []
    if missing:
        conflicts.append("Missing declared unit: " + ", ".join(missing))
    if undeclared:
        conflicts.append("Repository-associated units not declared: " + ", ".join(undeclared))
    if owned and set(owned) != set(declared):
        conflicts.append("Lifecycle owned_units differs from declared services")
    for item in known:
        if (item["load_state"] != "loaded" or
                item["active_state"] == "unknown" or
                not item["source_workdir_matches"]):
            conflicts.append("Unable to attest service checkout: " + item["unit"])
    return {
        "application": manifest["application"]["name"],
        "services": known,
        "missing": missing,
        "undeclared": undeclared,
        "conflicts": conflicts,
        "ready_for_reconciliation": not conflicts,
        "deployment_allowed": False,
        "write_operations": 0,
    }
