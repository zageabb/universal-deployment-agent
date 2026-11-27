"""Combined release transaction rehearsal. Only self-created disposable labs.

Uses actual staged payload bytes, synthetic installed identities and venv
markers. No live destination, systemctl, dependency installation or activation.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import tempfile
import fcntl
from contextlib import contextmanager

from tools import uda_install_journal as j
from tools import uda_integrated_install_rehearsal as files
from tools import uda_parallel_venv as venv
from tools.uda_runtime_integrity import inventory, regular_file

REPLACE = {"runtime/dashboard.py", "runtime/deploy_agent.py",
           "runtime/templates/dashboard.html", "runtime/home.py",
           "runtime/proxy_config.py", "runtime/proxy_migration_agent.py"}


@contextmanager
def locked(root):
    files.journal.validate_lab(root)
    fd = os.open(root / "combined.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def record(root, phase):
    j.durable_write(root / "combined.json", json.dumps({"version": 1, "phase": phase}).encode())


def phase(root):
    value = json.loads((root / "combined.json").read_text())
    if value["version"] != 1:
        raise ValueError("Unknown combined journal")
    return value["phase"]


def apply(root, manifest, crash):
    with locked(root):
        if (root / "combined.json").exists():
            raise ValueError("Existing combined transaction")
        record(root, "applying_files")
        # Translate a combined boundary into the file journal crash point.
        file_crash = "after:" + sorted(manifest)[len(manifest)//2] if crash == "during_files" else ""
        files.apply(root, manifest, file_crash)
        files.interrupt("after_files", crash)
        record(root, "switching_venv")
        venv.switch(root / "uda-venv-lab-dependencies",
                    interrupt=lambda point: files.interrupt(point, crash))
        files.interrupt("after_venv", crash)
        record(root, "awaiting_health")
        files.interrupt("awaiting_health", crash)


def recover(root, manifest, crash):
    with locked(root):
        if phase(root) not in {"applying_files", "switching_venv", "awaiting_health", "recovering", "rolled_back"}:
            raise ValueError("Unexpected combined phase")
        record(root, "recovering")
        dependency = root / "uda-venv-lab-dependencies"
        if (dependency / "journal.json").exists():
            venv.restore(dependency)
        elif venv.state(dependency) != ("old", "absent", "new"):
            raise ValueError("Unjournaled environment mutation")
        files.interrupt("after_venv_restore", crash)
        if (root / "journal.json").exists():
            if j.load(root)["phase"] != "rolled_back":
                file_crash = "restore:" + sorted(manifest)[len(manifest)//2] if crash == "during_restore" else ""
                files.recover(root, manifest, file_crash, activation_failed=True)
        record(root, "rolled_back")


SCENARIOS = ("success", "failed_health", "during_files", "after_files",
             "after_rename", "after_link", "after_venv", "awaiting_health",
             "after_venv_restore", "during_restore")


def rehearse(stage, scenario):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown scenario")
    payload = inventory(stage)["files"]
    with tempfile.TemporaryDirectory(prefix="uda-journal-lab-") as folder:
        root = Path(folder)
        for directory in ("runtime", "backup", "candidate"):
            (root / directory).mkdir(mode=0o700)
        dep = root / "uda-venv-lab-dependencies"
        dep.mkdir(mode=0o700)
        live, _, new = venv.layout(dep)
        for path, marker in ((live, "old"), (new, "new")):
            path.mkdir(mode=0o700)
            j.durable_write(path / ".uda-fixture", marker.encode())
        # The operator inventory identified six replacements and 35 adds.
        # Choose unchanged files by explicit existing V1 payload names below.
        unchanged = {"runtime/github_ci.py", "runtime/portal_auth.py",
                     "runtime/repo_visibility.py", "runtime/router_mapping.py",
                     "runtime/static/group-filter.js", "runtime/static/home.css",
                     "runtime/static/home.js", "runtime/templates/groups.html",
                     "runtime/templates/home.html", "runtime/templates/portal_form.html",
                     "runtime/templates/portal_user_detail.html",
                     "runtime/templates/portal_user_invite.html",
                     "runtime/templates/portal_users.html", "runtime/ui_groups.py"}
        preserve = unchanged | {n for n in payload if not n.startswith("runtime/")}
        manifest = {n: item for n, item in payload.items() if n not in preserve}
        if not REPLACE <= set(manifest) or not preserve <= set(payload):
            raise ValueError("Fixture inventory changed")
        for name, item in payload.items():
            for directory in ("runtime", "backup", "candidate"):
                (root / directory / name).parent.mkdir(parents=True, exist_ok=True)
            data = regular_file(stage, name).read_bytes()
            if j.checksum(data) != item["sha256"]:
                raise ValueError("Candidate changed")
            files.put(root / "candidate" / name, data, item["mode"])
            if name in preserve:
                files.put(root / "runtime" / name, data, item["mode"])
            elif name in REPLACE:
                files.put(root / "runtime" / name, ("prior:" + name).encode(), 0o640)
        sentinel = root / "runtime/unmanaged-state"
        files.put(sentinel, b"preserve", 0o600)
        before = {n: files.identity(root / "runtime" / n) for n in payload}
        recovery_crashes = {"after_venv_restore", "during_restore"}
        crash = "" if scenario in {"success", "failed_health"} | recovery_crashes else scenario
        files.run_child(apply, root, manifest, crash)
        if scenario == "success":
            if phase(root) != "awaiting_health" or venv.state(dep) != ("candidate_link", "old", "new"):
                raise RuntimeError("Candidate not ready")
            expected = {n: {"sha256": e["sha256"], "mode": e["mode"]} for n, e in payload.items()}
            if any(files.identity(root / "runtime" / n) != e for n, e in expected.items()):
                raise RuntimeError("Candidate payload mismatch")
            # Synthetic health acceptance, not actual service health.
            record(root, "fixture_accepted")
        else:
            if scenario in recovery_crashes:
                files.run_child(recover, root, manifest, scenario)
            files.run_child(recover, root, manifest, "")
            files.run_child(recover, root, manifest, "")
            expected = before
            if phase(root) != "rolled_back" or venv.state(dep) != ("old", "absent", "new"):
                raise RuntimeError("Combined rollback incomplete")
        if any(files.identity(root / "runtime" / n) != e for n, e in expected.items()):
            raise RuntimeError("Final identity mismatch")
        if sentinel.read_bytes() != b"preserve":
            raise RuntimeError("Unmanaged state changed")
        return {"status": "PASS", "scenario": scenario, "phase": phase(root),
                "add_count": len(manifest) - len(REPLACE), "replace_count": len(REPLACE),
                "preserved_count": len(preserve), "payload_count": len(payload),
                "sigkill_injected": bool(crash or scenario in recovery_crashes),
                "synthetic_environment_markers": True, "production_files_modified": False,
                "systemctl_invoked": False, "production_upgrade_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--scenario", choices=SCENARIOS + ("all",), default="all")
    args = parser.parse_args()
    scenarios = SCENARIOS if args.scenario == "all" else (args.scenario,)
    print(json.dumps([rehearse(args.stage, scenario) for scenario in scenarios], indent=2))


if __name__ == "__main__":
    main()
