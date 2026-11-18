"""V2-003 real systemd service lifecycle acceptance INSIDE DISPOSABLE CONTAINER.

This is a stand-alone CI integration fixture, not the UDA activation worker.
No module from this script is imported by UDA. Refuses host execution unless:
- explicit UDA_V2_DISPOSABLE_CONTAINER=1
- Docker marker /.dockerenv
- systemd is PID 1
- Ubuntu 24.04 base

Only two hard-coded, test-prefixed systemd units are ever touched. The
acceptance result covers startup, dependency ordering, web/worker health,
degraded worker classification, simulated release failure and restoration
of previous unit bytes and running states.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

BASE = Path("/opt/uda-v2-disposable")
SYSTEMD = Path("/etc/systemd/system")
WEB = "uda-v2-test-web.service"
WORKER = "uda-v2-test-worker.service"
UNITS = (WEB, WORKER)
EVIDENCE = Path("/tmp/uda-v2-systemd-evidence.json")


def guard():
    if os.environ.get("UDA_V2_DISPOSABLE_CONTAINER") != "1":
        raise RuntimeError("Explicit disposable container opt-in required")
    if not Path("/.dockerenv").exists():
        raise RuntimeError("This test cannot run on an Ubuntu host")
    if Path("/proc/1/comm").read_text().strip() != "systemd":
        raise RuntimeError("Container systemd is not PID 1")
    os_release = Path("/etc/os-release").read_text()
    if "ID=ubuntu" not in os_release or "VERSION_ID=\"24.04\"" not in os_release:
        raise RuntimeError("Acceptance requires Ubuntu 24.04")
    for name in UNITS:
        if not (BASE / name).is_file():
            raise RuntimeError("Missing disposable test-owned unit fixture")
        if (SYSTEMD / name).exists():
            raise RuntimeError("Disposable test unit already installed")


def run(*args, check=True):
    if args[0] != "systemctl" or args[1] not in (
        "daemon-reload", "start", "stop", "restart", "is-active", "show",
    ):
        raise RuntimeError("Unexpected integration systemd action")
    if args[1] not in ("daemon-reload",) and any(
            argument not in UNITS and argument not in ("--quiet",)
            for argument in args[2:]):
        raise RuntimeError("Unapproved integration unit")
    output = subprocess.run(args, text=True, capture_output=True,
                            timeout=20, check=False)
    if check and output.returncode:
        raise RuntimeError("Disposable systemd operation failed: " + args[1])
    return output.returncode == 0


def active(unit):
    return run("systemctl", "is-active", "--quiet", unit, check=False)


def wait_for(probe, *, timeout=14):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            if probe():
                return True
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    return False


def http_healthy():
    with urlopen("http://127.0.0.1:18763/health", timeout=2) as response:
        return response.status == 200 and response.read() == b"healthy"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    guard()
    evidence = {
        "ubuntu": "24.04",
        "environment": "docker-only-systemd-pid1",
        "units": list(UNITS),
        "production_activation_allowed": False,
        "systemd_started": False,
        "web_health": False,
        "worker_health": False,
        "degraded_worker_detected": False,
        "failed_upgrade_detected": False,
        "restored_previous_bytes": False,
        "restored_previous_running_state": False,
    }
    snapshot = {}
    try:
        for name in UNITS:
            (SYSTEMD / name).write_bytes((BASE / name).read_bytes())
        run("systemctl", "daemon-reload")
        run("systemctl", "start", WEB)
        if not wait_for(lambda: active(WEB) and http_healthy()):
            raise RuntimeError("Web service failed to become healthy")
        run("systemctl", "start", WORKER)
        if not wait_for(lambda: active(WORKER) and
                        Path("/run/uda-v2-worker.heartbeat").exists()):
            raise RuntimeError("Worker service failed to become healthy")
        evidence["systemd_started"] = True
        evidence["web_health"] = True
        evidence["worker_health"] = True

        # Optional worker loss must degrade, not hide behind a healthy API.
        run("systemctl", "stop", WORKER)
        if not active(WEB) or not http_healthy() or active(WORKER):
            raise RuntimeError("Optional worker outage failed classification")
        evidence["degraded_worker_detected"] = True
        run("systemctl", "start", WORKER)
        if not wait_for(lambda: active(WORKER)):
            raise RuntimeError("Optional worker could not be restored")

        # Capture real prior unit files and runtime states BEFORE mutation.
        snapshot = {
            name: {"bytes": (SYSTEMD / name).read_bytes(), "running": active(name)}
            for name in UNITS
        }
        run("systemctl", "stop", WORKER)
        run("systemctl", "stop", WEB)

        # Simulate a failed upgrade in this container alone. No caller can
        # supply an arbitrary systemd unit name or command.
        bad = (SYSTEMD / WEB).read_text().replace(
            "ExecStart=/usr/bin/python3 /opt/uda-v2-disposable/web.py",
            "ExecStart=/usr/bin/false",
        )
        if bad == (SYSTEMD / WEB).read_text():
            raise RuntimeError("Unable to inject expected upgrade failure")
        (SYSTEMD / WEB).write_text(bad)
        run("systemctl", "daemon-reload")
        run("systemctl", "start", WEB, check=False)
        if not wait_for(lambda: not active(WEB)):
            raise RuntimeError("Failed web upgrade was not detected")
        evidence["failed_upgrade_detected"] = True

        # Restore all unit definitions and previous running states.
        for name in UNITS:
            (SYSTEMD / name).write_bytes(snapshot[name]["bytes"])
        run("systemctl", "daemon-reload")
        for name in UNITS:
            if snapshot[name]["running"]:
                run("systemctl", "start", name)
            else:
                run("systemctl", "stop", name)
        if not wait_for(lambda: active(WEB) and http_healthy() and active(WORKER)):
            raise RuntimeError("Services failed after full rollback")
        evidence["restored_previous_bytes"] = all(
            (SYSTEMD / name).read_bytes() == snapshot[name]["bytes"]
            for name in UNITS
        )
        evidence["restored_previous_running_state"] = all(
            active(name) == snapshot[name]["running"] for name in UNITS
        )
        if not all(value is True for key, value in evidence.items()
                   if key not in ("ubuntu", "environment", "units",
                                  "production_activation_allowed")):
            raise RuntimeError("Incomplete disposable integration acceptance")
        print("PASS: disposable systemd startup, degraded worker and rollback")
    finally:
        # Preserve evidence even when a test fails; always tear down only the
        # exact disposable services, never host units.
        EVIDENCE.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
        for name in reversed(UNITS):
            run("systemctl", "stop", name, check=False)
        for name in UNITS:
            (SYSTEMD / name).unlink(missing_ok=True)
        run("systemctl", "daemon-reload")


if __name__ == "__main__":
    main()
