"""Backup inventory and archive verification for explicitly selected roots.

No live backup command or extraction into production. The caller must
establish writer quiescence and select all required production roots.
"""
import hashlib
import os
import re
from pathlib import Path
import sqlite3
import stat
import tarfile
import tempfile

from tools.uda_backup_coverage import safe_name
from tools.uda_production_release_plan import digest


def hash_stream(stream):
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        h.update(chunk)
    return h.hexdigest()


def fingerprint(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid,
            s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)


def reviewed_git_object(name):
    return re.fullmatch(
        r"runtime/(?:publishers/lucky-lab/\.git|remotes/lucky-lab\.git)/objects/"
        r"(?:[0-9a-f]{2}/[0-9a-f]{38}|pack/pack-[0-9a-f]{40}\.(?:pack|idx|rev))",
        name) is not None


def capture(roots, *, selected=None, excluded=()):
    excluded = set(excluded)
    selected = selected or {}
    entries = {}
    def visit(path, name):
        safe_name(name)
        before = path.lstat()
        item = {"mode": stat.S_IMODE(before.st_mode), "uid": before.st_uid,
                "gid": before.st_gid}
        if stat.S_ISLNK(before.st_mode):
            item.update(type="symlink", target=os.readlink(path))
        elif stat.S_ISDIR(before.st_mode):
            item.update(type="directory")
            entries[name] = item
            for child in sorted(path.iterdir()):
                child_name = name + "/" + child.name
                if child_name in excluded:
                    continue
                if selected.get(name) is not None and child.name not in selected[name]:
                    continue
                visit(child, child_name)
        elif stat.S_ISREG(before.st_mode) and (before.st_nlink == 1 or reviewed_git_object(name)):
            if before.st_nlink > 1:
                if before.st_uid != os.getuid():
                    raise ValueError("Unexpected Git object owner: " + name)
                item["source_link_count"] = before.st_nlink
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                if fingerprint(os.fstat(stream.fileno())) != fingerprint(before):
                    raise ValueError("Backup source changed: " + name)
                item.update(type="file", size=before.st_size, sha256=hash_stream(stream))
                if fingerprint(os.fstat(stream.fileno())) != fingerprint(before):
                    raise ValueError("Backup source changed: " + name)
        else:
            raise ValueError("Unsupported backup source: " + name)
        if fingerprint(path.lstat()) != fingerprint(before):
            raise ValueError("Backup source changed: " + name)
        entries[name] = item
    if not roots:
        raise ValueError("No backup roots")
    for name, path in sorted(roots.items()):
        safe_name(name)
        if "/" in name or path.is_symlink() or not path.is_dir():
            raise ValueError("Unsafe backup root")
        visit(path, name)
    return entries


def write_selected(tar, roots, inventory):
    """Store each selected regular file independently, including Git aliases.

    Clear tar's inode cache before each nonrecursive add so that the archive
    cannot contain hardlink references to another member or an omitted path.
    """
    for name in sorted(inventory):
        safe_name(name)
        label, _, relative = name.partition("/")
        path = roots[label] / relative if relative else roots[label]
        tar.inodes.clear()
        tar.add(path, arcname=name, recursive=False)


def sqlite_check(path):
    # Immutable mode is only suitable for a standalone, checkpointed copy.
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            raise ValueError("SQLite sidecar requires consistent snapshot")
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
    return True


def verify(archive, expected, sqlite_members=()):
    if not expected:
        raise ValueError("Empty backup inventory")
    databases = set(sqlite_members)
    if not databases <= set(expected):
        raise ValueError("Missing SQLite inventory")
    for name in databases:
        if expected[name]["type"] != "file" or any(name + suffix in expected for suffix in ("-wal", "-shm", "-journal")):
            raise ValueError("SQLite snapshot is not standalone")
    seen = set()
    checked = set()
    with tempfile.TemporaryDirectory(prefix="uda-backup-check-") as folder:
        with tarfile.open(archive, "r:*") as tar:
            for member in tar:
                name = safe_name(member.name)
                if name in seen or name not in expected:
                    raise ValueError("Unexpected or duplicate archive member: " + name)
                item = expected[name]
                if (member.mode, member.uid, member.gid) != (item["mode"], item["uid"], item["gid"]):
                    raise ValueError("Archive metadata mismatch: " + name)
                kind = item["type"]
                if kind == "directory" and member.isdir():
                    pass
                elif kind == "symlink" and member.issym() and member.linkname == item["target"]:
                    pass
                elif kind == "file" and member.isfile() and not member.issparse() and member.size == item["size"]:
                    with tar.extractfile(member) as stream:
                        if name in databases:
                            copy = Path(folder) / "database"
                            h = hashlib.sha256()
                            with copy.open("xb") as out:
                                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                    h.update(chunk)
                                    out.write(chunk)
                            actual = h.hexdigest()
                            if actual != item["sha256"]:
                                raise ValueError("Archive content mismatch: " + name)
                            sqlite_check(copy)
                            copy.unlink()
                            checked.add(name)
                        else:
                            actual = hash_stream(stream)
                        if actual != item["sha256"]:
                            raise ValueError("Archive content mismatch: " + name)
                else:
                    raise ValueError("Archive type or link mismatch: " + name)
                seen.add(name)
    if seen != set(expected) or checked != databases:
        raise ValueError("Missing archive members")
    return {"status": "INVENTORY_PASS", "entries": len(seen),
            "inventory_sha256": digest(expected), "sqlite_checked": sorted(checked),
            "application_consistency_verified": False,
            "production_upgrade_authorized": False}


def verify_snapshot(archive, roots, before, sqlite_members=(), *, selected=None, excluded=()):
    report = verify(archive, before, sqlite_members)
    if capture(roots, selected=selected, excluded=excluded) != before:
        raise ValueError("Backup source inventory drift")
    return report
