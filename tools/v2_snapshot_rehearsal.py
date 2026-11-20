"""UDA V1 pre-upgrade snapshot and disposable verification.

Explicitly invoked by an operator. NO production restore, installer, systemd,
network, Caddy or permission changes outside /media/t/uda-release.
Snapshots copy live *non-SQLite* files while running: true application-wide
consistency still requires a maintenance/quiescence window.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tarfile
import tempfile

DEFAULT_ROOT = Path("/media/t/uda-release")
SOURCES = {
    "runtime": Path.home() / ".local/share/deployment-agent",
    "config": Path.home() / ".config/deployment-agent",
    "state": Path.home() / ".local/state/deployment-agent",
    "systemd-user": Path.home() / ".config/systemd/user",
}
SQLITE_FILENAMES = {"identity.db", "identity.sqlite3"}
ARCHIVE_NAME = "uda-preupgrade.tar.gz"


class SnapshotError(RuntimeError):
    pass


def check_destination(root: Path, *, mountpoint: Path = Path("/media/t")) -> None:
    root = root.absolute()
    mountpoint = mountpoint.absolute()
    if not mountpoint.is_mount():
        raise SnapshotError("Backup destination mount is not mounted")
    if root != mountpoint / "uda-release":
        raise SnapshotError("Refusing unexpected destination")
    if root.is_symlink() or not root.is_dir():
        raise SnapshotError("Backup workspace is not a regular directory")
    if root.stat().st_uid != os.getuid() or stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise SnapshotError("Backup workspace must be owner-only 0700")
    for name in ("snapshots", "restore-rehearsals", "evidence"):
        child = root / name
        if child.is_symlink() or not child.is_dir():
            raise SnapshotError("Required private backup directory unavailable")
        m = child.stat()
        if m.st_uid != os.getuid() or stat.S_IMODE(m.st_mode) != 0o700:
            raise SnapshotError("Backup subdirectories must be owner-only 0700")


def _copy(source: Path, target: Path, *, label: str) -> None:
    if source.is_symlink() or not source.is_dir():
        raise SnapshotError(f"{label} source is not a directory")
    if label != "state":
        shutil.copytree(source, target, symlinks=True)
        return
    def ignore(folder: str, names: list[str]) -> set[str]:
        current = Path(folder)
        if current == source:
            return set(SQLITE_FILENAMES) & set(names)
        return set()
    shutil.copytree(source, target, symlinks=True, ignore=ignore)
    for name in SQLITE_FILENAMES:
        db_source = source / name
        if not db_source.exists():
            raise SnapshotError(f"Expected identity file missing: {name}")
        if db_source.is_symlink() or not db_source.is_file():
            raise SnapshotError(f"Unsafe identity file: {name}")
        if db_source.stat().st_size == 0:
            (target / name).touch(mode=0o600)
            continue
        # SQLite online backup produces a consistent DB image even if writers
        # are active; the rest of the application files are not transactionally
        # frozen and still need maintenance-window sign-off.
        uri = f"{db_source.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=10) as src:
            with sqlite3.connect(target / name) as dest:
                src.backup(dest, pages=64, sleep=0.05)
                if dest.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise SnapshotError("Identity SQLite backup integrity failed")


def snapshot(root: Path = DEFAULT_ROOT, sources: dict[str, Path] | None = None,
             *, mountpoint: Path = Path("/media/t")) -> Path:
    check_destination(root, mountpoint=mountpoint)
    paths = sources or SOURCES
    if set(paths) != set(SOURCES):
        raise SnapshotError("Source set is incomplete or unexpected")
    marker = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parent = root / "snapshots"
    with tempfile.TemporaryDirectory(prefix=".uda-stage-", dir=parent) as stage:
        stage_dir = Path(stage)
        data = stage_dir / "payload"
        data.mkdir(mode=0o700)
        for label, src in paths.items():
            _copy(src, data / label, label=label)
        dest = parent / f"uda-{marker}"
        if dest.exists():
            raise SnapshotError("Snapshot name collision")
        dest.mkdir(mode=0o700)
        try:
            archive = dest / ARCHIVE_NAME
            with tarfile.open(archive, "w:gz", dereference=False) as tf:
                for label in sorted(paths):
                    tf.add(data / label, arcname=label, recursive=True)
            archive.chmod(0o600)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            evidence = {
                "kind": "uda_preupgrade_snapshot",
                "sha256": digest,
                "archive": ARCHIVE_NAME,
                "source_groups": sorted(paths),
                "sqlite_backup_api_used": True,
                "application_wide_consistency_verified": False,
                "restoration_into_production_performed": False,
                "production_upgrade_authorized": False,
            }
            (dest / "manifest.json").write_text(json.dumps(evidence, indent=2) + "\n")
            (dest / "manifest.json").chmod(0o600)
            return dest
        except BaseException:
            shutil.rmtree(dest)
            raise


def rehearse(snapshot_dir: Path, root: Path = DEFAULT_ROOT,
            *, mountpoint: Path = Path("/media/t")) -> dict:
    check_destination(root, mountpoint=mountpoint)
    archive = snapshot_dir / ARCHIVE_NAME
    manifest = json.loads((snapshot_dir / "manifest.json").read_text())
    if manifest.get("archive") != ARCHIVE_NAME:
        raise SnapshotError("Unexpected manifest archive")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != manifest["sha256"]:
        raise SnapshotError("Archive SHA-256 mismatch")
    # Do not use extractall. Restrict to regular files/directories under a
    # new disposable root. Record symlinks as metadata, never materialize
    # untrusted symlinks, hardlinks or special files.
    with tempfile.TemporaryDirectory(prefix="uda-rehearsal-",
                                     dir=root / "restore-rehearsals") as tmp:
        out = Path(tmp)
        links = []
        regular_count = 0
        with tarfile.open(archive, "r:gz") as tf:
            for item in tf:
                path = Path(item.name)
                if (path.is_absolute() or ".." in path.parts or
                        not path.parts or path.parts[0] not in SOURCES):
                    raise SnapshotError("Unsafe archive path")
                dest = out.joinpath(*path.parts)
                if item.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                elif item.isfile():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    src = tf.extractfile(item)
                    if src is None:
                        raise SnapshotError("Archive entry unreadable")
                    with src, open(dest, "xb") as handle:
                        shutil.copyfileobj(src, handle)
                    regular_count += 1
                elif item.issym():
                    links.append({"path": item.name, "target": item.linkname})
                else:
                    raise SnapshotError("Archive contains unsupported entry")
        db = out / "state" / "identity.db"
        if not db.exists():
            raise SnapshotError("Identity SQLite absent from rehearsal")
        with sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True) as conn:
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise SnapshotError("Rehearsed SQLite integrity failed")
        required = [out / x for x in (
            "runtime/deploy_agent.py", "runtime/dashboard.py",
            "config/config.json", "state/identity.sqlite3",
            "systemd-user/deployment-agent.service",
            "systemd-user/deployment-agent-dashboard.service.d/10-environment.conf",
            "systemd-user/deployment-agent-home.service.d/10-environment.conf",
        )]
        if not all(x.is_file() for x in required):
            raise SnapshotError("Critical rollback asset absent")
        return {
            "archive_sha256_ok": True, "sqlite_quick_check": "ok",
            "regular_files_verified": regular_count,
            "symlinks_recorded_not_recreated": len(links),
            "disposable_extraction": True,
            "full_systemd_restore_rehearsed": False,
            "production_restore_performed": False,
            "production_upgrade_authorized": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "rehearse"))
    parser.add_argument("--snapshot-dir", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "snapshot":
            result = {"snapshot_directory": str(snapshot())}
        else:
            if args.snapshot_dir is None:
                parser.error("rehearse requires --snapshot-dir")
            result = rehearse(args.snapshot_dir)
    except (SnapshotError, OSError, sqlite3.Error, ValueError, tarfile.TarError) as exc:
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps({"status": "PASS", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
