"""Throwaway child process for genuine SIGKILL crash/restart acceptance.

Never runs systemctl or host services. All writes are restricted to the private
temporary test folder supplied by the parent pytest. A child process is
killed abruptly to test what its successor can verify on disk.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from onboarding_v2_multiservice import simulate_multiservice_release
from onboarding_v2_recovery_journal import DurableServiceJournal
from onboarding_v2_recovery_preflight import save_recovery_evidence
from onboarding_v2_unit_sandbox import UnitSandboxAdapter

def main() -> None:
    control = json.loads(Path(sys.argv[1]).read_text())
    sandbox = Path(control["sandbox"])
    journal_root = Path(control["journal_root"])
    snapshot_root = Path(control["snapshot_root"])
    names = control["service_units"]
    bundle = json.loads(Path(control["bundle_file"]).read_text())
    manifest = json.loads(Path(control["manifest_file"]).read_text())
    transaction_id = control["transaction_id"]
    mode = control["mode"]
    running = {"web"}

    adapter = UnitSandboxAdapter(
        sandbox=sandbox, unit_names=names,
        rendered_units={name: bundle["units"][unit].encode()
                        for name, unit in names.items()},
        is_running=lambda name: name in running,
        start_unit=lambda name: running.add(name),
        stop_unit=lambda name: running.discard(name),
        health_probe=lambda name, health: True,
    )
    def persist(captured: dict) -> None:
        old = {
            unit: {"bytes": captured[name]["bytes"],
                   "running": captured[name]["running"]}
            for name, unit in names.items()
        }
        save_recovery_evidence(snapshot_root, transaction_id, bundle, old, names)
        if mode == "after_snapshot":
            os.kill(os.getpid(), signal.SIGKILL)

    if mode == "during_configure":
        original = adapter.configure
        def configure(name: str, snapshot: object) -> None:
            original(name, snapshot)
            os.kill(os.getpid(), signal.SIGKILL)
        adapter.configure = configure

    journal = DurableServiceJournal(journal_root, transaction_id)
    simulate_multiservice_release(
        manifest, adapter, journal=journal,
        before_mutation=persist, simulation_only=True,
    )
    raise RuntimeError("Crash test child unexpectedly survived")

if __name__ == "__main__":
    main()
