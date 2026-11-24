"""CI-only real systemd timer rollback using synthetic, fixed-name fixtures."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from lifecycle_acceptance import guard as lifecycle_guard

ROOT = Path("/etc/systemd/system")
NAMES = ("uda-v2-test-timer-a.timer", "uda-v2-test-timer-b.timer",
         "uda-v2-test-timer-c.timer")
SERVICES = tuple(name.replace(".timer", ".service") for name in NAMES)
UNITS = NAMES + SERVICES
EVIDENCE = Path("/tmp/uda-v2-timer-restore.json")
TIMER = "[Unit]\nDescription=UDA disposable timer\n[Timer]\nOnActiveSec=1d\n[Install]\nWantedBy=timers.target\n"
SERVICE = "[Unit]\nDescription=UDA disposable oneshot\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"


def ctl(action, unit=None, *, check=True):
    if action == "daemon-reload":
        if unit is not None:
            raise ValueError("Unexpected unit")
        args = []
    elif action in {"start", "stop", "enable", "disable", "is-active", "is-enabled"} and unit in UNITS:
        args = [unit]
    else:
        raise ValueError("Unapproved systemd operation")
    result = subprocess.run(["systemctl", action, *args], capture_output=True,
                            text=True, timeout=25, check=False)
    if check and result.returncode:
        raise RuntimeError("Disposable systemd operation failed: " + action)
    return result


def states():
    result = {}
    for name in NAMES:
        active = ctl("is-active", name, check=False)
        enabled = ctl("is-enabled", name, check=False)
        a, e = active.stdout.strip(), enabled.stdout.strip()
        if (a, active.returncode) not in {("active", 0), ("inactive", 3)}:
            raise RuntimeError("Unexpected timer active state")
        if (e, enabled.returncode) not in {("enabled", 0), ("disabled", 1)}:
            raise RuntimeError("Unexpected timer enablement state")
        result[name] = {"active": a, "enabled": e}
    return result


def main():
    lifecycle_guard()
    for name in UNITS:
        if (ROOT / name).exists() or (ROOT / name).is_symlink():
            raise RuntimeError("Disposable fixture already exists")
    evidence = {"production_upgrade_authorized": False,
                "synthetic_units_only": True, "restored_timer_states": False,
                "restored_unit_bytes": False, "mutation_detected": False,
                "paired_services_healthy": False}
    owned = []
    try:
        for name in UNITS:
            with (ROOT / name).open("x") as f:
                owned.append(name)
                f.write(TIMER if name in NAMES else SERVICE)
        ctl("daemon-reload")
        # Exercise enabled+active, enabled+inactive, disabled+active independently.
        ctl("enable", NAMES[0])
        ctl("enable", NAMES[1])
        ctl("start", NAMES[0])
        ctl("start", NAMES[2])
        original = states()
        expected = dict(zip(NAMES, (
            {"active": "active", "enabled": "enabled"},
            {"active": "inactive", "enabled": "enabled"},
            {"active": "active", "enabled": "disabled"},
        )))
        if original != expected:
            raise RuntimeError("Baseline mismatch")
        evidence["baseline"] = original
        files = {name: (ROOT / name).read_bytes() for name in UNITS}
        for name in NAMES:
            ctl("stop", name)
            ctl("disable", name)
        ctl("enable", NAMES[2])
        ctl("start", NAMES[1])
        (ROOT / SERVICES[0]).write_text(SERVICE.replace("/usr/bin/true", "/usr/bin/false"))
        ctl("daemon-reload")
        failed = ctl("start", SERVICES[0], check=False)
        if not failed.returncode or states() == original:
            raise RuntimeError("Failed upgrade or state mutation not observed")
        evidence["mutation_detected"] = True
        for name in NAMES:
            ctl("stop", name)
        for name, data in files.items():
            (ROOT / name).write_bytes(data)
        ctl("daemon-reload")
        for name, state in original.items():
            ctl("enable" if state["enabled"] == "enabled" else "disable", name)
            if state["active"] == "active":
                ctl("start", name)
        evidence["restored"] = states()
        evidence["restored_timer_states"] = evidence["restored"] == original
        evidence["restored_unit_bytes"] = all((ROOT / n).read_bytes() == b for n, b in files.items())
        for name in SERVICES:
            ctl("start", name)
        evidence["paired_services_healthy"] = True
        if not all(evidence[k] for k in ("restored_timer_states", "restored_unit_bytes",
                                        "mutation_detected", "paired_services_healthy")):
            raise RuntimeError("Incomplete timer rollback")
        print("PASS: disposable timer enablement, active states and paired service rollback")
    finally:
        EVIDENCE.write_text(json.dumps(evidence, indent=2) + "\n")
        for name in NAMES:
            if name in owned:
                ctl("stop", name, check=False)
                ctl("disable", name, check=False)
        for name in SERVICES:
            if name in owned:
                ctl("stop", name, check=False)
        for name in owned:
            (ROOT / name).unlink(missing_ok=True)
        ctl("daemon-reload")


if __name__ == "__main__":
    main()
