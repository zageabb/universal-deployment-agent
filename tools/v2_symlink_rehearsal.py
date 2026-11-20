"""Offline UDA backup symlink audit: inspect archive members, never extract links.

This is *not* a systemd restore. It validates archive paths, records whether
symlink targets resolve inside the archived tree, and classifies absolute or
external targets for operator review. No link is created or followed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from tools.v2_snapshot_rehearsal import ARCHIVE_NAME, SOURCES, SnapshotError


def _parts(path: str) -> tuple[str, ...]:
    if not path or path.startswith("/") or "\x00" in path or "\\" in path:
        raise SnapshotError("Unsafe archived path")
    parts = tuple(path.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        raise SnapshotError("Noncanonical archived path")
    if parts[0] not in SOURCES:
        raise SnapshotError("Unexpected archive root")
    return parts


def _resolve_relative(link_parts: tuple[str, ...], target: str) -> tuple[str, ...] | None:
    base = list(link_parts[:-1])
    for part in target.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if len(base) <= 1:
                return None
            base.pop()
        else:
            base.append(part)
    return tuple(base)


def audit(snapshot_dir: Path) -> dict:
    if snapshot_dir.is_symlink() or not snapshot_dir.is_dir():
        raise SnapshotError("Snapshot directory unavailable")
    archive = snapshot_dir / ARCHIVE_NAME
    manifest = json.loads((snapshot_dir / "manifest.json").read_text())
    if manifest.get("archive") != ARCHIVE_NAME:
        raise SnapshotError("Unexpected snapshot manifest")
    if not isinstance(manifest.get("sha256"), str):
        raise SnapshotError("Manifest missing checksum")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != manifest["sha256"]:
        raise SnapshotError("Archive checksum mismatch")

    paths: dict[tuple[str, ...], str] = {}
    links: list[tuple[tuple[str, ...], str]] = []
    with tarfile.open(archive, "r:gz") as tf:
        for entry in tf:
            parts = _parts(entry.name.rstrip("/"))
            if parts in paths:
                raise SnapshotError("Duplicate archive member")
            if not (entry.isfile() or entry.isdir() or entry.issym()):
                raise SnapshotError("Unsupported archive entry type")
            paths[parts] = "dir" if entry.isdir() else ("link" if entry.issym() else "file")
            if entry.issym():
                links.append((parts, entry.linkname))

    counts = {"internal_regular_target": 0, "internal_link_target": 0,
              "missing_internal_target": 0, "outside_archive": 0,
              "absolute_target": 0, "invalid_target": 0}
    review: list[dict[str, str]] = []
    for parts, target in links:
        status: str
        if not target or "\x00" in target or "\\" in target:
            status = "invalid_target"
        elif target.startswith("/"):
            status = "absolute_target"
        else:
            resolved = _resolve_relative(parts, target)
            if resolved is None:
                status = "outside_archive"
            elif resolved not in paths:
                status = "missing_internal_target"
            elif paths[resolved] == "link":
                status = "internal_link_target"
            else:
                status = "internal_regular_target"
        counts[status] += 1
        if status != "internal_regular_target":
            # No raw target text: absolute link values can expose paths and
            # reviewer-specific details. Names under systemd are metadata.
            review.append({"member": "/".join(parts), "status": status})
    return {
        "status": "PASS" if not counts["invalid_target"] else "REVIEW_REQUIRED",
        "archive_checksum_ok": True,
        "link_count": len(links),
        "classification": counts,
        "review_entries": review,
        "links_recreated": False,
        "systemd_enablement_restored": False,
        "full_systemd_restore_rehearsed": False,
        "production_restore_performed": False,
        "production_upgrade_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.snapshot_dir)
    except (SnapshotError, OSError, ValueError, tarfile.TarError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
