"""Rebuild only UDA systemd enablement links inside a disposable tree.

No calls to systemctl, installers, Caddy, or production paths. Absolute targets
from archived .wants links are *never* recreated as absolute links: only exact
unit-file suffixes under the archived systemd-user root are mapped to private
copies of the matching archived regular unit file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tempfile

if __package__ in (None, ""):
    from v2_snapshot_rehearsal import ARCHIVE_NAME, DEFAULT_ROOT, SnapshotError, check_destination
else:
    from tools.v2_snapshot_rehearsal import ARCHIVE_NAME, DEFAULT_ROOT, SnapshotError, check_destination

# Intentional allowlist: unrelated app enablement links are not created.
ENABLED = {
    "default.target.wants/deployment-agent-dashboard.service":
        "deployment-agent-dashboard.service",
    "default.target.wants/deployment-agent-home.service":
        "deployment-agent-home.service",
    "timers.target.wants/deployment-agent.timer": "deployment-agent.timer",
    "timers.target.wants/uda-proxy-refresh.timer": "uda-proxy-refresh.timer",
    "timers.target.wants/uda-proxy-migration.timer": "uda-proxy-migration.timer",
}
OVERRIDES = (
    "deployment-agent-dashboard.service.d/10-environment.conf",
    "deployment-agent-home.service.d/10-environment.conf",
)


def _valid_member(name: str) -> bool:
    if not name or name.startswith("/") or "\x00" in name or "\\" in name:
        return False
    return all(p not in ("", ".", "..") for p in name.rstrip("/").split("/"))


def _validated_target(raw: str, unit: str) -> bool:
    if not raw or "\x00" in raw or "\\" in raw:
        return False
    if raw.startswith("/"):
        # The absolute systemd target must specifically refer to the
        # archived user's unit directory. No /etc or /usr/lib remapping.
        return raw.endswith("/.config/systemd/user/" + unit) and (
            len(PurePosixPath(raw).parts) >= 7
        ) and ".." not in PurePosixPath(raw).parts
    return raw == "../" + unit


def rehearse_units(snapshot_dir: Path, *, root: Path = DEFAULT_ROOT,
                   mountpoint: Path = Path("/media/t")) -> dict:
    check_destination(root, mountpoint=mountpoint)
    snapshots = root / "snapshots"
    if snapshot_dir.parent != snapshots or snapshot_dir.is_symlink():
        raise SnapshotError("Snapshot must be a direct child of private snapshots")
    archive = snapshot_dir / ARCHIVE_NAME
    if archive.is_symlink() or not archive.is_file():
        raise SnapshotError("Snapshot archive unavailable")
    manifest_path = snapshot_dir / "manifest.json"
    if manifest_path.is_symlink():
        raise SnapshotError("Unsafe snapshot manifest")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("archive") != ARCHIVE_NAME:
        raise SnapshotError("Unexpected snapshot manifest")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != manifest.get("sha256"):
        raise SnapshotError("Snapshot SHA-256 mismatch")

    needed = {
        "systemd-user/" + name: "link" for name in ENABLED
    } | {
        "systemd-user/" + name: "file" for name in (*ENABLED.values(), *OVERRIDES)
    }
    selected = {}
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf:
            if not _valid_member(member.name):
                raise SnapshotError("Unsafe archive member path")
            name = member.name.rstrip("/")
            if name in selected:
                raise SnapshotError("Duplicate required member")
            if name not in needed:
                continue
            expected = needed[name]
            if (expected == "link" and not member.issym()) or (
                expected == "file" and not member.isfile()
            ):
                raise SnapshotError("Required archived member has unsafe type")
            if expected == "file" and member.size > 1024 * 1024:
                raise SnapshotError("Unexpectedly large unit or drop-in")
            selected[name] = member
        if selected.keys() != needed.keys():
            raise SnapshotError("Required UDA systemd units/links/overrides missing")
        for link, unit in ENABLED.items():
            if not _validated_target(selected["systemd-user/" + link].linkname, unit):
                raise SnapshotError("Unsafe UDA systemd symlink target")

        with tempfile.TemporaryDirectory(
            prefix="uda-systemd-rehearsal-", dir=root / "restore-rehearsals"
        ) as temp:
            folder = Path(temp) / "systemd-user"
            folder.mkdir(mode=0o700)
            for unit in (*ENABLED.values(), *OVERRIDES):
                dest = folder / unit
                dest.parent.mkdir(parents=True, exist_ok=True)
                source = tf.extractfile(selected["systemd-user/" + unit])
                if source is None:
                    raise SnapshotError("Archived unit contents unreadable")
                with source, dest.open("xb") as writer:
                    while block := source.read(65536):
                        writer.write(block)
            for link, unit in ENABLED.items():
                dest = folder / link
                dest.parent.mkdir(parents=True, exist_ok=True)
                target = folder / unit
                dest.symlink_to(os.path.relpath(target, dest.parent))
                if not dest.is_file() or dest.resolve() != target.resolve():
                    raise SnapshotError("Disposable enablement link failed")
            return {
                "status": "PASS",
                "snapshot_sha256_ok": True,
                "uda_links_reconstructed": len(ENABLED),
                "uda_unit_files_present": len(ENABLED),
                "environment_overrides_present": len(OVERRIDES),
                "unrelated_links_reconstructed": 0,
                "disposable_links_resolved": True,
                "production_symlinks_modified": False,
                "systemctl_invoked": False,
                "full_systemd_restore_rehearsed": False,
                "production_upgrade_authorized": False,
            }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = rehearse_units(args.snapshot_dir)
    except (SnapshotError, OSError, ValueError, json.JSONDecodeError,
            tarfile.TarError) as exc:
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
