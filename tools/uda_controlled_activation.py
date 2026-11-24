"""Pure activation planning and in-memory acceptance model.

No subprocess, network, filesystem or production execution adapter exists.
"""
from dataclasses import dataclass

TIMERS = ("deployment-agent.timer", "uda-proxy-refresh.timer", "uda-proxy-migration.timer")
WORKERS = ("deployment-agent.service", "uda-proxy-refresh.service", "uda-proxy-migration.service")
WEB = ("deployment-agent-home.service", "deployment-agent-dashboard.service")
UNITS = TIMERS + WORKERS + WEB


@dataclass(frozen=True)
class State:
    active: str
    enabled: str
    loaded: str = "loaded"
    sub: str = ""
    result: str = "success"


def validate(states):
    if set(states) != set(UNITS):
        raise ValueError("Incomplete or unexpected unit inventory")
    for unit, state in states.items():
        if state.loaded != "loaded" or state.result != "success":
            raise ValueError("Unhealthy unit: " + unit)
        if state.active not in {"active", "inactive"}:
            raise ValueError("Unstable unit: " + unit)
        if state.enabled not in {"enabled", "disabled", "static"}:
            raise ValueError("Unknown enablement: " + unit)
        if unit in TIMERS and state.enabled == "static":
            raise ValueError("Unexpected timer enablement")
        expected = "dead" if state.active == "inactive" else ("waiting" if unit in TIMERS else "running")
        if state.sub != expected:
            raise ValueError("Unexpected substate: " + unit)


def admission(original, isolated, *, writers_quiescent, backup_verified):
    validate(original)
    validate(isolated)
    if not writers_quiescent or not backup_verified:
        raise ValueError("Isolation or backup evidence missing")
    if any(original[u].active != "inactive" for u in WORKERS):
        raise ValueError("Original worker running")
    if any(isolated[u].active != "inactive" for u in UNITS):
        raise ValueError("Maintenance isolation incomplete")
    if any(original[u].enabled != isolated[u].enabled for u in UNITS):
        raise ValueError("Enablement changed during isolation")


def plan(original):
    validate(original)
    return tuple(("start", u) for u in WEB if original[u].active == "active") + (
        ("health", "home"), ("health", "dashboard"),
    ) + tuple(("start", u) for u in TIMERS if original[u].active == "active")


class Model:
    """Synthetic state only; cannot invoke a real service or health endpoint."""
    def __init__(self, states, health=None, fail_start=None):
        self.states = dict(states)
        self.health = {"home": True, "dashboard": True} if health is None else dict(health)
        self.fail_start = fail_start
        self.events = []
        self.caddy = "unchanged"
        self.unrelated = "unchanged"

    def start(self, unit):
        if unit not in WEB + TIMERS:
            raise ValueError("Unit not allowed")
        self.events.append(("start", unit))
        if unit == self.fail_start:
            self.fail_start = None
            raise RuntimeError("Synthetic start failure")
        s = self.states[unit]
        self.states[unit] = State("active", s.enabled, sub="waiting" if unit in TIMERS else "running")

    def stop(self, unit):
        if unit not in WEB + TIMERS:
            raise ValueError("Unit not allowed")
        self.events.append(("stop", unit))
        s = self.states[unit]
        self.states[unit] = State("inactive", s.enabled, sub="dead")

    def probe(self, target):
        self.events.append(("health", target))
        return self.health.get(target) is True

    def rollback_payload(self):
        self.events.append(("rollback", "payload"))
        return True


def rehearse(original, isolated, *, writers_quiescent=True, backup_verified=True, health=None,
             fail_start=None):
    admission(original, isolated, writers_quiescent=writers_quiescent, backup_verified=backup_verified)
    # This increment supports the known host topology with both web services active.
    if any(original[u].active != "active" for u in WEB):
        raise ValueError("Both original web services must be active")
    model = Model(isolated, health, fail_start)
    outcome = "activated"
    try:
        for action, target in plan(original):
            if action == "start":
                model.start(target)
            elif not model.probe(target):
                raise RuntimeError("Synthetic health failure")
        if model.states != original:
            raise RuntimeError("State mismatch")
    except RuntimeError:
        # Stop timers first, then web, before rollback. Never resume timers if
        # rollback or old-runtime health is not verified.
        for unit in TIMERS + tuple(reversed(WEB)):
            if model.states[unit].active == "active":
                model.stop(unit)
        if not model.rollback_payload():
            raise RuntimeError("Rollback not verified")
        for unit in WEB:
            model.start(unit)
        # Model the old runtime independently of candidate health.
        model.events.append(("health", "restored-home"))
        model.events.append(("health", "restored-dashboard"))
        for unit in TIMERS:
            if original[unit].active == "active":
                model.start(unit)
        if model.states != original:
            raise RuntimeError("Rollback state mismatch")
        outcome = "rolled_back"
    return {"outcome": outcome, "events": model.events, "original_states_restored": model.states == original,
            "caddy_unchanged": model.caddy == "unchanged", "unrelated_unchanged": model.unrelated == "unchanged",
            "production_upgrade_authorized": False, "systemctl_invoked": False}
