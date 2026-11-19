"""Read-only host readiness evidence for a future UDA V2 maintenance window.

This module does not pause timers, modify Caddy, deploy, or acquire production
locks. It inspects only two explicit user timers/services and the kernel's
Ubuntu version. Output contains no secrets or arbitrary environment content.
Even a 'ready_for_scheduling' report is not permission to deploy.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

OS_SUPPORTED = {"22.04", "24.04"}
TIMERS = ("deployment-agent.timer", "uda-proxy-refresh.timer")
SERVICES = ("deployment-agent.service", "uda-proxy-refresh.service")
ALLOWED = (*TIMERS, *SERVICES)
MAX_OUTPUT = 4096


def _read_status(unit: str, runner) -> dict:
    if unit not in ALLOWED:
        raise ValueError("Unapproved systemd unit")
    command = [
        "systemctl", "--user", "show", "--no-pager",
        "--property=LoadState,ActiveState,SubState,UnitFileState,NextElapseUSecRealtime",
        "--", unit,
    ]
    result = runner(command, capture_output=True, text=True,
                    check=False, timeout=8)
    if result.returncode != 0 or len(result.stdout) > MAX_OUTPUT:
        return {"unit": unit, "state": "unknown", "inspection_error": True}
    parsed = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in {"LoadState", "ActiveState", "SubState",
                           "UnitFileState", "NextElapseUSecRealtime"}:
            parsed[key] = value[:150]
    if not {"LoadState", "ActiveState"}.issubset(parsed):
        return {"unit": unit, "state": "unknown", "inspection_error": True}
    return {
        "unit": unit, "state": parsed["ActiveState"],
        "load_state": parsed["LoadState"],
        "sub_state": parsed.get("SubState", "unknown"),
        "unit_file_state": parsed.get("UnitFileState", "unknown"),
        "next_elapse": parsed.get("NextElapseUSecRealtime", ""),
        "inspection_error": False,
    }


def inspect_host(*, runner=subprocess.run,
                 os_release: Path = Path("/etc/os-release")) -> dict:
    """Read-only report; never declares host mutation or deployment approved."""
    data = os_release.read_text(encoding="utf-8")
    m = re.search(r'^VERSION_ID="?([^"\n]+)"?$', data, flags=re.MULTILINE)
    ubuntu = bool(re.search(r"^ID=ubuntu$", data, flags=re.MULTILINE))
    version = m.group(1) if m else ""
    items = {unit: _read_status(unit, runner) for unit in ALLOWED}
    errors = [
        "unsupported_ubuntu" if not ubuntu or version not in OS_SUPPORTED else None,
        "timer_inspection_incomplete" if any(
            items[u]["inspection_error"] for u in TIMERS) else None,
        "service_inspection_incomplete" if any(
            items[u]["inspection_error"] for u in SERVICES) else None,
        "production_deployment_timer_active" if items[TIMERS[0]]["state"] == "active" else None,
        "production_proxy_timer_active" if items[TIMERS[1]]["state"] == "active" else None,
        "deployment_oneshot_active" if items[SERVICES[0]]["state"] in
            {"active", "activating", "deactivating"} else None,
        "proxy_refresh_active" if items[SERVICES[1]]["state"] in
            {"active", "activating", "deactivating"} else None,
    ]
    blockers = [e for e in errors if e]
    return {
        "target": "local_user_systemd",
        "ubuntu_version": version,
        "units": items,
        "maintenance_isolation_blockers": blockers,
        "ready_for_isolated_test_scheduling": not blockers,
        "deployment_allowed": False,
        "timer_mutation_allowed": False,
        "production_activation_allowed": False,
        "lock_holder_verified": False,
        "note": ("Advisory only: before a separately approved host test, verify "
                 "the production deployment lock, app/port isolation, current "
                 "git revisions, and restore timer states after maintenance."),
    }


def main() -> int:
    try:
        result = inspect_host()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({
            "ready_for_isolated_test_scheduling": False,
            "deployment_allowed": False,
            "inspection_error": type(exc).__name__,
        }))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ready_for_isolated_test_scheduling"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
