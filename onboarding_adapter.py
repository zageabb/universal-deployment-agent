"""Transaction-scoped local activation adapter.

This adapter writes only paths explicitly supplied by the trusted caller and
delegates service/health/Caddy activation to injected operations. It is NOT
exposed through the UDA dashboard and must not be used against production
until worker isolation and restart recovery are reviewed.
"""
from __future__ import annotations

from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import secrets
from typing import Callable

from onboarding import OnboardingError
from onboarding_preflight import deployment_preflight
from onboarding_registry import inactive_registry_entry
from onboarding_release import verify_prepared_release, systemd_unit_preview
from onboarding_recovery import save_snapshot
from proxy_config import render as render_caddy


def _read_existing(path: Path) -> bytes | None:
    if path.is_symlink():
        raise OnboardingError("Managed configuration path is a symlink")
    return path.read_bytes() if path.exists() else None


def _write_atomic(path: Path, value: bytes) -> None:
    if path.is_symlink():
        raise OnboardingError("Managed configuration path is a symlink")
    if path.parent.is_symlink():
        raise OnboardingError("Managed configuration parent may not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise OnboardingError("Managed configuration parent may not be a symlink")
    current_mode = (path.stat().st_mode & 0o777) if path.exists() else 0o600
    temp = path.with_name("." + path.name + "." + secrets.token_hex(8) + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, current_mode)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(value)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _restore(path: Path, snapshot: bytes | None) -> None:
    if snapshot is None:
        if path.is_symlink():
            raise OnboardingError("Cannot remove linked managed file")
        path.unlink(missing_ok=True)
    else:
        _write_atomic(path, snapshot)


class LocalActivationAdapter:
    """Injected IO-only implementation of the InstallAdapter protocol.

    The caller is responsible for running it under a dedicated unprivileged
    account with a restricted path allowlist, and for persistent journaling.
    """
    def __init__(
        self, *,
        registry_path: Path,
        unit_path: Path,
        proxy_path: Path,
        attestation_path: Path,
        environment_path: Path,
        lock_path: Path,
        service_start: Callable[[str], None],
        service_stop: Callable[[str], None],
        proxy_reload: Callable[[], None],
        health_probe: Callable[[str], None],
        auth_probe: Callable[[str], None],
        runtime_probe: Callable[[str], str],
        service_exists: Callable[[str], bool],
        port_available: Callable[[int], bool],
        snapshot_root: Path | None = None,
    ):
        self.registry_path = registry_path
        self.unit_path = unit_path
        self.proxy_path = proxy_path
        self.attestation_path = attestation_path
        self.environment_path = environment_path
        self.lock_path = lock_path
        self.service_start = service_start
        self.service_stop = service_stop
        self.proxy_reload = proxy_reload
        self.health_probe = health_probe
        self.auth_probe = auth_probe
        self.runtime_probe = runtime_probe
        self.service_exists = service_exists
        self.port_available = port_available
        self.snapshot_root = snapshot_root
        self._lock_file = None

    def acquire_lock(self) -> None:
        if self.lock_path.is_symlink():
            raise OnboardingError("Lock must not be a symlink")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        file = self.lock_path.open("a")
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            file.close()
            raise
        self._lock_file = file

    def release_lock(self) -> None:
        if self._lock_file is not None:
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None

    def capture_snapshot(self, transaction_id: str) -> object:
        snapshot = {
            "transaction_id": transaction_id,
            "registry": _read_existing(self.registry_path),
            "unit": _read_existing(self.unit_path),
            "proxy": _read_existing(self.proxy_path),
            "attestation": _read_existing(self.attestation_path),
        }
        # Explicitly configured durable store must commit before any mutation.
        if self.snapshot_root is not None:
            save_snapshot(self.snapshot_root, transaction_id, snapshot)
        return snapshot

    def _registry(self) -> dict:
        try:
            value = json.loads(self.registry_path.read_text())
        except (OSError, ValueError) as exc:
            raise OnboardingError("UDA registry is unreadable") from exc
        if not isinstance(value, dict) or not isinstance(value.get("applications"), list):
            raise OnboardingError("Invalid UDA registry")
        return value

    def preflight(self, plan: dict, release: dict) -> None:
        if self.registry_path.is_symlink() or self.unit_path.is_symlink() or self.proxy_path.is_symlink():
            raise OnboardingError("Managed configuration cannot be symlinked")
        self._require_paths(plan)
        deployment_preflight(
            release, plan, self._registry(),
            environment_file=self.environment_path,
            service_exists=self.service_exists, port_available=self.port_available,
        )

    def _require_paths(self, plan: dict) -> None:
        if self.unit_path.name != plan.get("service_unit"):
            raise OnboardingError("Unexpected systemd unit path")
        if self.attestation_path.is_symlink():
            raise OnboardingError("Attestation cannot be symlinked")

    def configure_service(self, plan: dict, release: dict) -> None:
        text = systemd_unit_preview(
            plan, Path(release["release_path"]), environment_file=self.environment_path
        )
        _write_atomic(self.unit_path, text.replace(
            "# UDA installation PREVIEW ONLY; NOT activated",
            "# UDA reviewed activation transaction"
        ).encode())

    def start_service(self, plan: dict) -> None:
        self.service_start(plan["service_unit"])

    def verify_health(self, plan: dict, release: dict) -> None:
        self.health_probe(f"http://127.0.0.1:{plan['port']}{plan['health_path']}")

    def register_application(self, plan: dict, release: dict) -> None:
        registry = self._registry()
        entry = inactive_registry_entry(plan, release)
        if any(app.get("name") == entry["name"] for app in registry["applications"]):
            raise OnboardingError("Application registered concurrently")
        entry["enabled"] = True
        entry["onboarding_state"] = "health_verified"
        entry["proxy_enabled"] = bool(plan.get("proxy_path"))
        entry["show_on_home"] = bool(plan.get("proxy_path"))
        registry["applications"].append(entry)
        from deploy_agent import load_config
        # Validate exact proposed data before atomic publication.
        payload = json.dumps(registry, indent=2) + "\n"
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "registry.json"
            candidate.write_text(payload)
            load_config(candidate)
        _write_atomic(self.registry_path, payload.encode())

    def publish_proxy(self, plan: dict) -> None:
        cfg = self._registry()
        text = render_caddy(cfg)
        _write_atomic(self.proxy_path, text.encode())
        self.proxy_reload()

    def verify_authentication(self, plan: dict) -> None:
        if plan.get("proxy_path"):
            self.auth_probe(plan["proxy_path"])

    def verify_runtime_sha(self, plan: dict, release: dict) -> None:
        verify_prepared_release(Path(release["release_path"]), plan["commit_sha"])
        actual = self.runtime_probe(plan["application"])
        if actual != plan["commit_sha"]:
            raise OnboardingError("Runtime SHA does not match approved release")

    def record_attestation(self, plan: dict, release: dict) -> None:
        _write_atomic(self.attestation_path, (plan["commit_sha"] + "\n").encode())

    def compensate(self, step: str, snapshot: object, plan: dict) -> None:
        if not isinstance(snapshot, dict) or "transaction_id" not in snapshot:
            raise OnboardingError("Recovery snapshot unavailable")
        if step == "attestation":
            _restore(self.attestation_path, snapshot["attestation"])
        elif step == "proxy":
            _restore(self.proxy_path, snapshot["proxy"])
            self.proxy_reload()
        elif step == "registry":
            _restore(self.registry_path, snapshot["registry"])
        elif step == "start":
            self.service_stop(plan["service_unit"])
        elif step == "service":
            _restore(self.unit_path, snapshot["unit"])
        else:
            raise OnboardingError("Unknown compensation operation")
