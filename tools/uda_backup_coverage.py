"""Read-only tar coverage verification against an independently captured inventory.

Does not establish application consistency, capture quiescence or authorize
installation. No archive extraction, live writes or service actions.
"""
import hashlib
import tarfile
from pathlib import PurePosixPath


def safe_name(name):
    p = PurePosixPath(name)
    if p.is_absolute() or not p.parts or ".." in p.parts or str(p) != name:
        raise ValueError("Unsafe archive member: " + name)
    return name


def verify(archive, expected):
    """Expected maps exact regular-file archive paths to size/mode/SHA256.

    Directory and symlink metadata are not supported in this regular-file
    verification increment. Refuse unsupported objects rather than skip them.
    """
    if not expected:
        raise ValueError("Empty backup inventory")
    for name in expected:
        safe_name(name)
    seen = set()
    with tarfile.open(archive, "r:*") as tar:
        for member in tar:
            name = safe_name(member.name)
            if name in seen:
                raise ValueError("Duplicate archive member: " + name)
            if name not in expected:
                raise ValueError("Unexpected archive member: " + name)
            if not member.isfile() or member.issparse():
                raise ValueError("Unsupported archive member: " + name)
            item = expected[name]
            if member.size != item["size"] or member.mode != item["mode"]:
                raise ValueError("Archive metadata mismatch: " + name)
            h = hashlib.sha256()
            with tar.extractfile(member) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
            if h.hexdigest() != item["sha256"]:
                raise ValueError("Archive content mismatch: " + name)
            seen.add(name)
    if seen != set(expected):
        raise ValueError("Missing archive members")
    return {"status": "COVERAGE_PASS", "verified_files": len(seen),
            "regular_file_inventory_verified": True,
            "application_consistency_verified": False,
            "production_upgrade_authorized": False}
