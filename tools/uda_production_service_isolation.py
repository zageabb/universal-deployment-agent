"""Allowlisted user-systemd adapter and isolation sequencing.

No executable CLI. The future release controller must supply authorization,
hold the persistent transaction lock, and verify the fresh backup separately.
"""
from __future__ import annotations
import subprocess
import time
from tools.uda_controlled_activation import TIMERS, WORKERS, WEB, UNITS, validate
from tools.uda_production_admission import read_states, review_states

BUSY = {("activating", "start"), ("activating", "start-pre"),
        ("active", "running"), ("deactivating", "stop"),
        ("deactivating", "stop-sigterm")}


class UserSystemd:
    def snapshot(self):
        return read_states()

    def change(self, action, unit):
        if action not in {"start", "stop"} or unit not in TIMERS + WEB:
            raise ValueError("Service action not allowed")
        subprocess.run(["systemctl", "--user", action, unit], check=True,
                       capture_output=True, text=True, timeout=90)


def review(states, original):
    if set(states) != set(UNITS):
        raise ValueError("Unexpected unit inventory")
    for unit, state in states.items():
        if state.enabled != original[unit].enabled or state.loaded != "loaded" or state.result != "success":
            raise ValueError("Unexpected unit state: " + unit)


def drain(adapter, original, *, timeout=300, interval=2, clock=time.monotonic, sleep=time.sleep):
    if timeout <= 0 or interval <= 0:
        raise ValueError("Invalid drain timeout")
    deadline = clock() + timeout
    while True:
        states = adapter.snapshot()
        review(states, original)
        if any((states[u].active, states[u].sub) != ("inactive", "dead") for u in TIMERS):
            raise ValueError("Timer isolation lost")
        idle = True
        for u in WORKERS:
            pair = (states[u].active, states[u].sub)
            if pair != ("inactive", "dead"):
                if pair not in BUSY:
                    raise ValueError("Unexpected worker state: " + u)
                idle = False
        if idle:
            return states
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("Worker drain timed out; no worker killed")
        sleep(min(interval, remaining))


def isolate(adapter, journal, *, timeout=300, interval=2):
    from tools.uda_controlled_activation import State
    record = journal.load()
    if record["phase"] != "prepared":
        raise ValueError("Prepared transaction required")
    original = {u: State(**s) for u, s in record["plan"]["contract"]["original_states"].items()}
    review_states(original)
    current = adapter.snapshot()
    if current != original:
        raise ValueError("Baseline state drift")
    journal.advance("isolating")
    for unit in TIMERS:
        adapter.change("stop", unit)
    drain(adapter, original, timeout=timeout, interval=interval)
    for unit in reversed(WEB):
        adapter.change("stop", unit)
    final = adapter.snapshot()
    review(final, original)
    validate(final)
    if any(s.active != "inactive" for s in final.values()):
        raise ValueError("Isolation incomplete")
    journal.advance("isolated")
    return final


def restore(adapter, original, probe, *, timeout=300, interval=2):
    """Restore service availability only after payload recovery is verified by caller.

    Stop timers and drain workers first, then start web services and require
    both probes before restarting timers. Failed probes leave timers stopped.
    """
    review_states(original)
    states = adapter.snapshot()
    review(states, original)
    for unit in TIMERS:
        if states[unit].active != "inactive":
            adapter.change("stop", unit)
    drain(adapter, original, timeout=timeout, interval=interval)
    for unit in WEB:
        if adapter.snapshot()[unit] != original[unit]:
            adapter.change("start", unit)
    states = adapter.snapshot()
    review(states, original)
    if any(states[u] != original[u] for u in WEB):
        raise ValueError("Web service restoration incomplete")
    for target in ("home", "dashboard"):
        if probe(target) is not True:
            raise RuntimeError("Health verification failed: " + target)
    started = []
    try:
        for unit in TIMERS:
            started.append(unit)
            adapter.change("start", unit)
        states = adapter.snapshot()
        review(states, original)
        if states != original:
            # A normal timer may already have fired; do not claim acceptance.
            raise ValueError("Restored state differs from baseline")
    except Exception:
        for unit in reversed(started):
            adapter.change("stop", unit)
        raise
    return states
