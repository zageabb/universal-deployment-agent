"""Read-only concrete integrity checks for the release controller.

No maintenance authorization or backup attestation is implied.
"""
import os
import stat
import hashlib
from pathlib import Path
from tools.uda_production_payload_transaction import file_identity, expected, parents
from tools.uda_production_release_plan import digest
from tools.uda_controlled_activation import UNITS, validate
from tools.uda_production_admission import directory_review
from tools.uda_permanent_candidate_venv import identity


def preserved(plan, home):
    body = plan["contract"]
    if digest(body) != plan["sha256"]:
        raise ValueError("Contract digest mismatch")
    roots = {"runtime": home / ".local/share/deployment-agent",
             "units": home / ".config/systemd/user", "bin": home / ".local/bin"}
    if len(body["preserved"]) != 24 or set(body["units"]) != set(UNITS):
        raise ValueError("Incomplete preserved inventory")
    for name, item in list(body["preserved"].items()) + [
            ("units/" + u, v) for u, v in body["units"].items()]:
        kind, rel = name.split("/", 1)
        if kind not in roots or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise ValueError("Unsafe preserved path")
        parents(roots[kind], rel)
        if item["status"] != "present" or file_identity(roots[kind], rel) != expected(item):
            raise ValueError("Preserved file drift: " + name)
    return True


def environment(root):
    """Hash original environment without executing it or altering permissions."""
    directory_review(root)
    entries = {}
    def walk_error(exc):
        raise exc
    for folder, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        for name in sorted(dirs + files):
            path = Path(folder) / name
            rel = str(path.relative_to(root))
            before = path.lstat()
            mode = stat.S_IMODE(before.st_mode)
            if before.st_uid != os.getuid():
                raise ValueError("Unexpected environment owner: " + rel)
            if stat.S_ISLNK(before.st_mode):
                target = os.readlink(path)
                resolved = path.resolve(strict=True)
                if resolved.is_relative_to(root.resolve()):
                    entries[rel] = ["internal-link", target]
                elif rel.startswith("bin/") and Path(rel).name.startswith("python") and resolved.is_file() and resolved.stat().st_uid == 0 and not resolved.stat().st_mode & 0o022:
                    entries[rel] = ["interpreter", target, hashlib.sha256(resolved.read_bytes()).hexdigest()]
                else:
                    raise ValueError("Unexpected environment link: " + rel)
            elif stat.S_ISDIR(before.st_mode):
                directory_review(path)
                entries[rel] = ["directory", mode]
            elif stat.S_ISREG(before.st_mode) and before.st_nlink == 1:
                if mode & 0o002 or any(k.startswith("system.posix_acl_") for k in os.listxattr(path, follow_symlinks=False)):
                    raise ValueError("Unsafe environment file: " + rel)
                if mode & 0o020:
                    import grp
                    import pwd
                    from tools.uda_production_admission import private_group
                    if not private_group(os.getuid(), before.st_gid, pwd.getpwall(), grp.getgrgid(before.st_gid)):
                        raise ValueError("Non-private environment group: " + rel)
                entries[rel] = ["file", mode, hashlib.sha256(path.read_bytes()).hexdigest()]
            else:
                raise ValueError("Unsafe environment object: " + rel)
            after = path.lstat()
            if (before.st_dev, before.st_ino, before.st_mode, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_mode, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("Environment changed during scan: " + rel)
    return {"identity": list(identity(root)), "tree_sha256": digest(entries), "entries": len(entries)}


def verify_environment(root, receipt):
    if environment(root) != receipt:
        raise ValueError("Original environment drift")
    return True


def units_idle(adapter, original):
    states = adapter.snapshot()
    validate(states)
    if any(s.active != "inactive" or s.enabled != original[u].enabled for u,s in states.items()):
        raise ValueError("UDA units not isolated")
    return True
