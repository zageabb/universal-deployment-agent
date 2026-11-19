"""CI-only real systemd crash/restart acceptance on disposable Ubuntu.

Uses actual UDA V2 snapshot and hash-chained journal libraries. A child writes
an intent, overwrites ONLY a hard-coded disposable test unit and is terminated
with SIGKILL. A fresh parent process validates the manual recovery plan and
restores the previous configuration/running states. No automatic replay exists.

Never run against production Docker or a real host systemd instance.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import uuid

from lifecycle_acceptance import (
    BASE, SYSTEMD, WEB, WORKER, UNITS, guard, run, active, wait_for,
    http_healthy,
)

sys.path.insert(0, "/opt/uda-v2-source")
from onboarding_v2_recovery_journal import DurableServiceJournal
from onboarding_v2_recovery_preflight import (
    save_recovery_evidence, plan_interrupted_recovery,
)

STATE = BASE / "crash-state"
SOURCESHA = "a" * 40
MAPPING = {"web": WEB, "worker": WORKER}
UPGRADE_EXEC = "ExecStart=/usr/bin/false"
PRIOR_EXEC = "ExecStart=/usr/bin/python3 /opt/uda-v2-disposable/web.py"


def _assert_container(*, child=False):
    if not child:
        guard()  # Parent refuses to use an already installed test unit.
    else:
        # The child necessarily sees test units installed by the parent.
        if os.environ.get("UDA_V2_DISPOSABLE_CONTAINER") != "1":
            raise RuntimeError("Explicit disposable CI opt-in required")
        if not Path("/.dockerenv").exists():
            raise RuntimeError("Host systemd execution is forbidden")
        if Path("/proc/1/comm").read_text().strip() != "systemd":
            raise RuntimeError("Isolated systemd must be PID1")
        release = Path("/etc/os-release").read_text()
        if "ID=ubuntu" not in release or not any(
                f'VERSION_ID="{version}"' in release
                for version in ("22.04", "24.04")):
            raise RuntimeError("Unexpected Ubuntu version")
        if not all((BASE / unit).is_file() and (SYSTEMD / unit).is_file()
                   for unit in UNITS):
            raise RuntimeError("Missing fixed disposable test unit")
    if set(UNITS) != {WEB, WORKER}:
        raise RuntimeError("Invalid disposable unit allowlist")


def _bundle() -> dict:
    bad = (BASE / WEB).read_text().replace(PRIOR_EXEC, UPGRADE_EXEC)
    if bad == (BASE / WEB).read_text():
        raise RuntimeError("Expected hard-coded launcher absent")
    contents = {WEB: bad, WORKER: (BASE / WORKER).read_text()}
    hashes = {name: hashlib.sha256(text.encode()).hexdigest()
              for name, text in contents.items()}
    payload = {
        "application": "uda-v2-crash-test",
        "commit_sha": SOURCESHA,
        "order": [WEB, WORKER],
        "unit_hashes": hashes,
    }
    digest = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**payload, "bundle_sha256": digest, "units": contents,
            "approval_required": True, "deployment_allowed": False,
            "status": "review_only"}


def _child() -> None:
    _assert_container(child=True)
    control = json.loads((STATE / "control.json").read_text())
    transaction_id = control["transaction_id"]
    bundle = json.loads((STATE / "bundle.json").read_text())
    journal = DurableServiceJournal(STATE / "journal", transaction_id)
    originals = {
        unit: {"bytes": (SYSTEMD / unit).read_bytes(), "running": active(unit)}
        for unit in UNITS
    }
    if not all(item["running"] for item in originals.values()):
        raise RuntimeError("Cannot snapshot inactive baseline")
    save_recovery_evidence(
        STATE / "snapshots", transaction_id, bundle, originals, MAPPING)
    journal({"state": "preparing", "events": ["snapshot:web"],
             "pending_undo": []})
    journal({"state": "preparing", "events": ["snapshots_persisted"],
             "pending_undo": []})
    journal({"state": "applying", "events": ["intent:restore:web"],
             "pending_undo": ["restore:web"]})
    # The first real systemd unit-file mutation is AFTER all durable evidence.
    (SYSTEMD / WEB).write_text(bundle["units"][WEB])
    run("systemctl", "daemon-reload")
    os.kill(os.getpid(), signal.SIGKILL)
    raise RuntimeError("SIGKILL child survived")


def _parent() -> None:
    _assert_container()
    STATE.mkdir(mode=0o700)
    for name in ("journal", "snapshots"):
        (STATE / name).mkdir(mode=0o700)
    transaction_id = str(uuid.uuid4())
    bundle = _bundle()
    (STATE / "bundle.json").write_text(json.dumps(bundle))
    (STATE / "control.json").write_text(json.dumps(
        {"transaction_id": transaction_id}))
    original_bytes = {unit: (BASE / unit).read_bytes() for unit in UNITS}
    evidence = {
        "ubuntu": next(version for version in ("22.04", "24.04")
                       if f'VERSION_ID="{version}"' in Path("/etc/os-release").read_text()),
        "systemd_pid1": True,
        "sigkill_confirmed": False,
        "journal_survived": False,
        "pre_mutation_snapshot_survived": False,
        "manual_plan_reopened": False,
        "no_automatic_replay": False,
        "restored_previous_bytes": False,
        "restored_previous_running_state": False,
        "production_activation_allowed": False,
    }
    installed = False
    try:
        for unit in UNITS:
            if (SYSTEMD / unit).exists():
                raise RuntimeError("Disposable test unit already installed")
            (SYSTEMD / unit).write_bytes(original_bytes[unit])
        installed = True
        run("systemctl", "daemon-reload")
        run("systemctl", "start", WEB)
        run("systemctl", "start", WORKER)
        if not wait_for(lambda: active(WEB) and active(WORKER) and http_healthy()):
            raise RuntimeError("Baseline web and worker failed health")
        child = subprocess.run(
            ["/opt/uda-v2-test-venv/bin/python", str(Path(__file__).resolve()), "child"],
            env={**os.environ, "UDA_V2_DISPOSABLE_CONTAINER": "1"},
            capture_output=True, text=True, timeout=30, check=False)
        if child.returncode != -signal.SIGKILL:
            raise RuntimeError("Child did not terminate with SIGKILL: " + child.stderr[-700:])
        evidence["sigkill_confirmed"] = True
        if (SYSTEMD / WEB).read_text() != bundle["units"][WEB]:
            raise RuntimeError("Crash occurred before real systemd unit mutation")
        journal = DurableServiceJournal(STATE / "journal", transaction_id)
        evidence["journal_survived"] = bool(journal.records())
        evidence["pre_mutation_snapshot_survived"] = (
            (STATE / "snapshots" / (transaction_id + ".json")).is_file())
        if not (evidence["journal_survived"] and evidence["pre_mutation_snapshot_survived"]):
            raise RuntimeError("Incomplete disk-backed recovery evidence")
        # New OS process reconstructs a plan without inheriting child state.
        plan = plan_interrupted_recovery(
            snapshot_root=STATE / "snapshots",
            journal_root=STATE / "journal",
            transaction_id=transaction_id, reviewed_bundle=bundle,
            service_units=MAPPING)
        if plan["pending_compensations"] != [
                {"operation": "restore", "service": "web", "unit": WEB}]:
            raise RuntimeError("Unexpected recovery compensation target")
        evidence["manual_plan_reopened"] = True
        evidence["no_automatic_replay"] = (
            plan["requires_operator_review"] is True and
            plan["can_execute"] is False and
            plan["automatic_replay_allowed"] is False and
            (SYSTEMD / WEB).read_text() == bundle["units"][WEB])
        if not evidence["no_automatic_replay"]:
            raise RuntimeError("Recovery preflight performed unauthorized writes")

        # Explicit test harness cleanup, NOT automatic UDA recovery.
        run("systemctl", "stop", WORKER)
        run("systemctl", "stop", WEB)
        for unit in UNITS:
            (SYSTEMD / unit).write_bytes(original_bytes[unit])
        run("systemctl", "daemon-reload")
        run("systemctl", "start", WEB)
        run("systemctl", "start", WORKER)
        if not wait_for(lambda: active(WEB) and active(WORKER) and http_healthy()):
            raise RuntimeError("Original services failed after test restoration")
        evidence["restored_previous_bytes"] = all(
            (SYSTEMD / unit).read_bytes() == original_bytes[unit] for unit in UNITS)
        evidence["restored_previous_running_state"] = all(active(unit) for unit in UNITS)
        expected = [
            "sigkill_confirmed", "journal_survived",
            "pre_mutation_snapshot_survived", "manual_plan_reopened",
            "no_automatic_replay", "restored_previous_bytes",
            "restored_previous_running_state",
        ]
        if not all(evidence[key] is True for key in expected):
            raise RuntimeError("Incomplete real systemd crash acceptance")
        print("PASS: disposable real systemd SIGKILL evidence and manual recovery review")
    finally:
        (BASE / "systemd-crash-evidence.json").write_text(json.dumps(
            evidence, indent=2, sort_keys=True) + "\n")
        if installed:
            for unit in reversed(UNITS):
                run("systemctl", "stop", unit, check=False)
            for unit in UNITS:
                (SYSTEMD / unit).unlink(missing_ok=True)
            run("systemctl", "daemon-reload")


if __name__ == "__main__":
    if sys.argv[1:] == ["child"]:
        _child()
    elif not sys.argv[1:]:
        _parent()
    else:
        raise RuntimeError("Invalid test mode")
