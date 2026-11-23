"""Read-only UDA release baseline; no installer, systemd mutations or secrets.

The output is a snapshot of observed control-plane metadata, not an
authorisation, live rollback test, Caddy/SSO proof, or deployment readiness.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

TIMERS = ("deployment-agent.timer", "uda-proxy-refresh.timer",
          "uda-proxy-migration.timer")
SERVICES = ("deployment-agent.service", "uda-proxy-refresh.service",
            "deployment-agent-dashboard.service",
            "deployment-agent-home.service")
PROPERTIES = ("LoadState", "ActiveState", "SubState", "UnitFileState",
              "Result", "ExecMainStatus", "NextElapseUSecRealtime")


def read_unit(unit: str, *, runner=subprocess.run) -> dict:
    cmd = ["systemctl", "--user", "show", "--no-pager",
           "--property=" + ",".join(PROPERTIES), unit]
    try:
        result = runner(cmd, capture_output=True, text=True, timeout=10,
                        check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {"unit": unit, "observation": "unavailable"}
    if result.returncode != 0:
        return {"unit": unit, "observation": "unavailable",
                "exit_code": result.returncode}
    values = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in PROPERTIES:
            values[key] = value
    if not values or "LoadState" not in values:
        return {"unit": unit, "observation": "incomplete"}
    return {"unit": unit, "observation": "collected", "properties": values}


def collect(*, runner=subprocess.run) -> dict:
    data = [read_unit(unit, runner=runner) for unit in (*TIMERS, *SERVICES)]
    return {
        "kind": "uda_v2_read_only_host_baseline",
        "units": data,
        "unit_metadata_collected": sum(
            u["observation"] == "collected" for u in data),
        "required_unit_count": len(data),
        "timer_state_changed": False,
        "service_action_performed": False,
        "caddy_health_verified": False,
        "sso_health_verified": False,
        "application_health_verified": False,
        "installed_runtime_rollback_verified": False,
        "production_upgrade_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        help="Optional owner-private JSON report path")
    args = parser.parse_args()
    report = collect()
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        # Fail on existing paths. Explicitly owner-only for fresh reports.
        with args.output.open("x", encoding="utf-8") as output:
            args.output.chmod(0o600)
            output.write(text)
        print(json.dumps({"report_written": str(args.output),
                          "unit_metadata_collected":
                          report["unit_metadata_collected"]}))
    else:
        print(text, end="")
    # Incomplete inspection is not a successful release gate.
    return 0 if report["unit_metadata_collected"] == report[
        "required_unit_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
