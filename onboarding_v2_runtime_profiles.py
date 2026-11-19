"""Review-only Python virtualenv runtime attestations for UDA v2 systemd units.

A virtualenv is provisioned OUTSIDE the verified source release by a separately
trusted build workflow. This module never creates an environment, installs
dependencies, runs Python, imports application code, or performs any host write.

An external reviewer supplies expected executable/pyvenv.cfg SHA-256 digests.
All metadata is verified again at render time. This only permits a reviewed
launch plan; it grants no execution capability.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat

from onboarding import OnboardingError

HEX64 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
VENV_ENTRY = ".venv/bin/python"
MAX_FILE = 8 * 1024 * 1024
MAX_CONFIG = 32 * 1024


def _regular_hash(path: Path, *, max_bytes: int) -> str:
    try:
        st = path.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes or st.st_size <= 0:
            raise OnboardingError("Unacceptable reviewed runtime artifact")
        if st.st_mode & stat.S_IWOTH:
            raise OnboardingError("Reviewed runtime artifact is world-writable")
        with path.open("rb") as handle:
            content = handle.read(max_bytes + 1)
    except (OSError, ValueError) as exc:
        raise OnboardingError("Reviewed runtime artifact cannot be read") from exc
    if len(content) > max_bytes:
        raise OnboardingError("Reviewed runtime artifact exceeds bound")
    return hashlib.sha256(content).hexdigest()


def review_python_venv(profile: dict, *, release_commit: str) -> dict:
    """Return an attested interpreter path if everything matches review evidence.

    The policy is intentionally more restrictive than ordinary Python venvs:
    the virtualenv directory must be a private, actual directory; bin/python
    may be a symlink, but its final target must exactly equal a separately
    approved, absolute Python executable. Intermediate links are not trusted
    to exit the preapproved target. This is NOT an arbitrary executable allowlist.
    """
    if not isinstance(profile, dict) or set(profile) != {
        "type", "venv_root", "approved_python", "python_sha256",
        "config_sha256", "source_commit"
    } or profile["type"] != "python-venv":
        raise OnboardingError("Invalid reviewed virtualenv profile")
    if (not isinstance(release_commit, str) or not SHA40.fullmatch(release_commit) or
            profile["source_commit"] != release_commit):
        raise OnboardingError("Virtualenv is not bound to reviewed release commit")
    if any(not isinstance(profile[k], str) or not HEX64.fullmatch(profile[k])
           for k in ("python_sha256", "config_sha256")):
        raise OnboardingError("Missing trusted virtualenv artifact digests")
    root = profile["venv_root"]
    approved = profile["approved_python"]
    if (not isinstance(root, Path) or not root.is_absolute() or root.is_symlink() or
            not isinstance(approved, Path) or not approved.is_absolute() or
            approved.is_symlink()):
        raise OnboardingError("Virtualenv and Python paths must be absolute and non-symlinked")
    try:
        real_root = root.resolve(strict=True)
        approved_target = approved.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise OnboardingError("Reviewed Python runtime is missing") from exc
    if (not real_root.is_dir() or not (real_root / "bin").is_dir() or
            (real_root / "bin").is_symlink() or
            real_root.stat().st_mode & 0o022 or
            (real_root / "bin").stat().st_mode & 0o022):
        raise OnboardingError("Virtualenv directories must not be group/world writable")
    script = root / "bin" / "python"
    if not script.exists() or script.is_dir():
        raise OnboardingError("Reviewed virtualenv python is absent")
    # A symlinked venv interpreter is legitimate, but must resolve to the
    # exact independently reviewed system interpreter file.
    try:
        actual_target = script.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise OnboardingError("Virtualenv Python link cannot be resolved") from exc
    if actual_target != approved_target:
        raise OnboardingError("Virtualenv Python target differs from approved interpreter")
    if not os.access(actual_target, os.X_OK):
        raise OnboardingError("Approved Python runtime is not executable")
    cfg = root / "pyvenv.cfg"
    if cfg.is_symlink() or not cfg.is_file():
        raise OnboardingError("Virtualenv configuration must be a real file")
    if _regular_hash(actual_target, max_bytes=MAX_FILE) != profile["python_sha256"]:
        raise OnboardingError("Virtualenv Python digest mismatch")
    if _regular_hash(cfg, max_bytes=MAX_CONFIG) != profile["config_sha256"]:
        raise OnboardingError("Virtualenv configuration digest mismatch")
    # Do not export the runtime contents or any environmental secrets.
    return {
        "runtime": "python-venv",
        "resolved_entrypoint": str(script),
        "release_commit": release_commit,
        "python_sha256": profile["python_sha256"],
        "config_sha256": profile["config_sha256"],
        "review_only": True,
        "can_execute": False,
    }
