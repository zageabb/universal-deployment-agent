"""V2-003 isolated multi-unit filesystem adapter for disposable Ubuntu acceptance.

This adapter can only operate inside a caller-created PRIVATE directory under
the OS temporary root, and has *no* built-in systemctl, sudo, SSH, Caddy,
registry, installer or production activation hook. Its process lifecycle is
injected from a test harness. It is intentionally unsuitable for a live host.

Snapshots include both unit-file bytes and prior running state. On rollback,
the original unit configuration AND previous running state are restored.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Callable

from onboarding import OnboardingError
from onboarding_v2_ubuntu_preflight import _unit

MAX_UNIT_BYTES = 64 * 1024
UNIT_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _private_sandbox(path: Path) -> Path:
    """Require an existing non-symlink private directory under temp root."""
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        raise OnboardingError("Adapter requires a trusted absolute sandbox directory")
    base = Path(tempfile.gettempdir()).resolve()
    resolved = path.resolve(strict=True)
    if resolved == base or not resolved.is_relative_to(base):
        raise OnboardingError("Adapter is forbidden outside the temporary sandbox")
    if not resolved.is_dir() or resolved.stat().st_mode & 0o077:
        raise OnboardingError("Sandbox directory must be private")
    # The entire subordinate unit tree is created by the adapter only.
    return resolved


def _unit_path(root: Path, unit: str) -> Path:
    _unit(unit)
    path = root / "units" / unit
    if path.is_symlink() or path.parent.is_symlink():
        raise OnboardingError("Unit or unit directory cannot be symlinked")
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise OnboardingError("Unit path is not a regular unique file")
    return path


def _atomic(path: Path, content: bytes | None) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise OnboardingError("Unit target cannot be symlinked")
    if content is None:
        path.unlink(missing_ok=True)
        return
    if not isinstance(content, bytes) or len(content) > MAX_UNIT_BYTES:
        raise OnboardingError("Invalid unit content")
    tmp = path.with_name("." + path.name + "." + os.urandom(8).hex() + ".tmp")
    flags = os.O_CREAT | os.O_WRONLY | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as writer:
            writer.write(content)
            writer.flush()
            os.fsync(fd)
        if path.is_symlink():
            raise OnboardingError("Unit target changed into symlink")
        os.replace(tmp, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        os.close(fd)
        tmp.unlink(missing_ok=True)


class UnitSandboxAdapter:
    """Implements the V2-003 injected SimulationAdapter contract for fake units."""

    def __init__(self, *, sandbox: Path, unit_names: dict[str, str],
                 rendered_units: dict[str, bytes], is_running: Callable[[str], bool],
                 start_unit: Callable[[str], None], stop_unit: Callable[[str], None],
                 health_probe: Callable[[str, str], bool]):
        self.root = _private_sandbox(sandbox)
        if (not isinstance(unit_names, dict) or not unit_names or
                len(unit_names) > 20 or set(unit_names) != set(rendered_units)):
            raise OnboardingError("Sandbox units and templates must match")
        if (any(not isinstance(name, str) or not UNIT_NAME.fullmatch(name)
                for name in unit_names) or
                len(set(unit_names.values())) != len(unit_names)):
            raise OnboardingError("Invalid or repeated sandbox service identity")
        for unit in unit_names.values():
            _unit(unit)
        for name, content in rendered_units.items():
            if (not isinstance(content, bytes) or not content or
                    len(content) > MAX_UNIT_BYTES or b"\x00" in content):
                raise OnboardingError("Invalid reviewed unit template")
        for handler in (is_running, start_unit, stop_unit, health_probe):
            if not callable(handler):
                raise OnboardingError("Sandbox service callbacks must be explicitly injected")
        self.units = dict(unit_names)
        self.templates = dict(rendered_units)
        self.is_running = is_running
        self.start_unit = start_unit
        self.stop_unit = stop_unit
        self.health_probe = health_probe
        self._lock = None

    def acquire_lock(self) -> None:
        if self._lock is not None:
            raise OnboardingError("Adapter lock already held")
        lock = self.root / ".uda-sandbox.lock"
        if lock.is_symlink():
            raise OnboardingError("Sandbox lock cannot be symlinked")
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(lock, flags, 0o600)
        try:
            if os.fstat(fd).st_mode & 0o077:
                raise OnboardingError("Sandbox lock is not private")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise
        self._lock = fd

    def release_lock(self) -> None:
        if self._lock is not None:
            fd, self._lock = self._lock, None
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _path(self, name: str) -> Path:
        if name not in self.units:
            raise OnboardingError("Undeclared sandbox service")
        units = self.root / "units"
        if units.is_symlink():
            raise OnboardingError("Sandbox units directory cannot be symlinked")
        units.mkdir(mode=0o700, exist_ok=True)
        if units.stat().st_mode & 0o077:
            raise OnboardingError("Sandbox units directory not private")
        return _unit_path(self.root, self.units[name])

    def capture_snapshot(self, name: str) -> dict:
        path = self._path(name)
        content = path.read_bytes() if path.exists() else None
        if content is not None and len(content) > MAX_UNIT_BYTES:
            raise OnboardingError("Prior unit exceeds size bound")
        return {
            "name": name, "bytes": content,
            "sha256": hashlib.sha256(content).hexdigest() if content is not None else None,
            "running": bool(self.is_running(name)),
        }

    def configure(self, name: str, snapshot: object) -> None:
        if not isinstance(snapshot, dict) or snapshot.get("name") != name:
            raise OnboardingError("Invalid sandbox recovery snapshot")
        # Do not trust the manifest as a unit template; templates come only
        # from a separately reviewed caller, never from manifest entrypoints.
        _atomic(self._path(name), self.templates[name])

    def start(self, name: str) -> None:
        self._path(name)
        self.start_unit(name)

    def check_health(self, name: str, health_type: str) -> bool:
        self._path(name)
        if health_type not in ("http", "process", "tcp", "command"):
            raise OnboardingError("Unknown sandbox health probe")
        return bool(self.health_probe(name, health_type))

    def stop(self, name: str) -> None:
        self._path(name)
        self.stop_unit(name)

    def restore(self, name: str, snapshot: object) -> None:
        if not isinstance(snapshot, dict) or snapshot.get("name") != name:
            raise OnboardingError("Snapshot does not belong to service")
        content = snapshot.get("bytes")
        expected = snapshot.get("sha256")
        if (content is not None and (not isinstance(content, bytes) or
                hashlib.sha256(content).hexdigest() != expected)):
            raise OnboardingError("Recovery unit snapshot integrity mismatch")
        if content is None and expected is not None:
            raise OnboardingError("Invalid empty unit snapshot hash")
        _atomic(self._path(name), content)
        # Restoring configuration is not enough; reproduce previous runtime
        # state for an upgrade of a running service.
        if snapshot.get("running"):
            self.start_unit(name)
        else:
            self.stop_unit(name)
