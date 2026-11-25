"""Read-only production replacement inventory. Never modifies live files.

Unit definitions and the command wrapper are review-only, not replacement
targets. The existing venv is not modified or executed by this inventory.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import stat
from collections import Counter

from tools.uda_runtime_integrity import inventory, digest
from tools.uda_controlled_activation import UNITS


def inspect(root, relative):
    path = root
    for part in (".", *Path(relative).parts):
        path = path / part
        try:
            info = path.lstat()
        except FileNotFoundError:
            return {"status": "missing"}
        if stat.S_ISLNK(info.st_mode):
            return {"status": "unsafe_symlink"}
        if path != root / relative and not stat.S_ISDIR(info.st_mode):
            return {"status": "unsafe_parent"}
    if not stat.S_ISREG(info.st_mode):
        return {"status": "not_regular"}
    if info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o022:
        return {"status": "unsafe_metadata"}
    if info.st_size > 8 * 1024 * 1024:
        return {"status": "oversized"}
    value = digest(path)
    after = path.lstat()
    if (info.st_ino, info.st_dev, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        return {"status": "changed_during_scan"}
    return {"status": "present", "sha256": value, "mode": stat.S_IMODE(info.st_mode)}


def collect(stage, home):
    manifest = inventory(stage)["files"]
    roots = {"runtime": home / ".local/share/deployment-agent",
             "units": home / ".config/systemd/user",
             "bin": home / ".local/bin"}
    entries = {}
    issues = []
    for name, item in manifest.items():
        kind, relative = name.split("/", 1)
        old = inspect(roots[kind], relative)
        if old["status"] not in {"present", "missing"}:
            issues.append(name + ": " + old["status"])
        if kind != "runtime":
            action = "preserve_review"
        elif old["status"] == "missing":
            action = "add"
        elif old["status"] != "present":
            action = "blocked"
        elif old["sha256"] == item["sha256"] and old["mode"] == item["mode"]:
            action = "unchanged"
        else:
            action = "replace"
        entries[name] = {"action": action, "installed": old, "candidate": item}
    # All eight existing units must be accounted for, including proxy refresh
    # units not shipped by the installer. Do not inspect drop-in contents.
    units = {u: inspect(roots["units"], u) for u in UNITS}
    for u, state in units.items():
        if state["status"] != "present":
            issues.append("unit:" + u + ": " + state["status"])
    for kind, root in roots.items():
        try:
            info = root.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o002:
                issues.append(kind + ": unsafe root")
            elif info.st_mode & 0o020:
                issues.append(kind + ": group-writable root requires review")
        except OSError:
            issues.append(kind + ": root unavailable")
    return {"status": "REVIEW" if issues else "PASS",
            "payload_count": len(entries), "actions": dict(Counter(e["action"] for e in entries.values())),
            "entries": entries, "units": units, "issues": issues,
            "dependencies_require_separate_review": True,
            "configuration_and_dropins_preserved": True,
            "production_files_modified": False, "systemctl_invoked": False,
            "production_upgrade_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = collect(args.stage, Path.home())
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["status"] == "PASS" else 1
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc),
                          "production_upgrade_authorized": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
