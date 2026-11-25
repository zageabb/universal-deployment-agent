"""Read-only release pre-admission for the known UDA production topology.

Reports a baseline, not permission to install. No services are stopped,
no configuration contents are exposed, and no candidate venv is created.
"""
from __future__ import annotations
import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess

from tools.uda_controlled_activation import State, UNITS, WEB, TIMERS, WORKERS, validate
from tools.uda_production_replacement_plan import collect

EXPECTED = {"add": 35, "replace": 3, "unchanged": 17, "preserve_review": 7}
REPLACEMENTS = {"runtime/dashboard.py", "runtime/deploy_agent.py",
                "runtime/templates/dashboard.html"}


def private_group(uid, gid, accounts, group):
    owners = {p.pw_name for p in accounts if p.pw_uid == uid}
    members = {p.pw_name for p in accounts if p.pw_gid == gid} | set(group.gr_mem)
    return len(owners) == 1 and members == owners


def directory_review(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o002:
        raise ValueError("Unsafe directory: " + str(path))
    if info.st_mode & 0o020 and not private_group(os.getuid(), info.st_gid, pwd.getpwall(), grp.getgrgid(info.st_gid)):
        raise ValueError("Non-private writable group: " + str(path))
    # Reject extended ACLs and default ACLs; absence is normal on Linux.
    for key in os.listxattr(path, follow_symlinks=False):
        if key.startswith("system.posix_acl_"):
            raise ValueError("Extended ACL requires review: " + str(path))


def review_inventory(report):
    if report["actions"] != EXPECTED or report["payload_count"] != 62:
        raise ValueError("Production payload scope changed")
    actual = {n for n, e in report["entries"].items() if e["action"] == "replace"}
    if actual != REPLACEMENTS:
        raise ValueError("Replacement set changed")
    for name, entry in report["entries"].items():
        if entry["action"] == "preserve_review":
            old, new = entry["installed"], entry["candidate"]
            if old["status"] != "present" or any(old[k] != new[k] for k in ("mode", "sha256")):
                raise ValueError("Preserved payload differs: " + name)
    allowed = {f"{k}: group-writable root requires review" for k in ("runtime", "units", "bin")}
    if set(report["issues"]) - allowed:
        raise ValueError("Unresolved inventory issues")


def read_states():
    states = {}
    for unit in UNITS:
        result = subprocess.run(["systemctl", "--user", "show", unit,
                                 "--property=ActiveState,SubState,UnitFileState,LoadState,Result"],
                                check=True, text=True, capture_output=True, timeout=15)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        states[unit] = State(values["ActiveState"], values["UnitFileState"],
                             values["LoadState"], values["SubState"], values.get("Result", "success") or "success")
    validate(states)
    return states


def review_states(states):
    validate(states)
    if any(states[u].active != "active" or states[u].enabled != "enabled" for u in WEB + TIMERS):
        raise ValueError("Known running topology changed")
    if any(states[u].active != "inactive" for u in WORKERS):
        raise ValueError("Worker active: retry read-only inspection when idle")


def inspect(stage):
    home = Path.home()
    runtime = home / ".local/share/deployment-agent"
    units = home / ".config/systemd/user"
    binary = home / ".local/bin"
    # Check existing ancestors and payload directories without following links.
    report = collect(stage, home)
    review_inventory(report)
    directories = {home, home / ".local", home / ".local/share", home / ".config",
                   home / ".config/systemd", runtime, units, binary}
    for name in report["entries"]:
        kind, rel = name.split("/", 1)
        root = {"runtime": runtime, "units": units, "bin": binary}[kind]
        parent = (root / rel).parent
        while parent != root:
            if parent.exists() or parent.is_symlink():
                directories.add(parent)
            parent = parent.parent
    for directory in sorted(directories):
        directory_review(directory)
    for name in ("venv-v2", "venv-v1-retained"):
        p = runtime / name
        if p.exists() or p.is_symlink():
            raise ValueError("Existing candidate or retained environment requires review")
    for p in (runtime / "venv", runtime / "venv/bin"):
        directory_review(p)
    states = read_states()
    review_states(states)
    return {"status": "BASELINE_PASS", "actions": report["actions"],
            "payload_count": report["payload_count"],
            "unit_states": {u: vars(s) for u, s in states.items()},
            "directory_group_review_passed": True,
            "production_files_modified": False, "systemctl_read_only": True,
            "fresh_backup_required": True, "candidate_venv_required": True,
            "maintenance_isolation_required": True,
            "production_upgrade_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(args.stage), indent=2))
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "REVIEW", "error": str(exc),
                          "production_upgrade_authorized": False}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
