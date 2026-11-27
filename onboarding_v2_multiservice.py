"""V2-003 multi-service transaction *simulation*, without privileged host IO.

Consumes strict UDA v2 systemd graphs. All effects are injected through a
test adapter; this module provides NO production systemd, Caddy, registry,
database, container or process implementation. Its only public entrypoint
is explicitly named simulate_multiservice_release to discourage accidental
use as a production activation path.

The durable journal callback must persist intent before any adapter mutation.
Partial failures register compensation BEFORE calling a mutating operation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from onboarding import OnboardingError
from uda_manifest_v2_validate import ManifestV2Error, validate as validate_v2


class SimulationAdapter(Protocol):
    def acquire_lock(self) -> None: ...
    def release_lock(self) -> None: ...
    def capture_snapshot(self, name: str) -> object: ...
    def configure(self, name: str, snapshot: object) -> None: ...
    def start(self, name: str) -> None: ...
    def check_health(self, name: str, health_type: str) -> bool: ...
    def stop(self, name: str) -> None: ...
    def restore(self, name: str, snapshot: object) -> None: ...


@dataclass
class MultiServiceResult:
    state: str = "not_started"
    application: str = ""
    order: list[str] = field(default_factory=list)
    healthy: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    compensated: list[str] = field(default_factory=list)
    pending_undo: list[str] = field(default_factory=list)
    rollback_errors: list[str] = field(default_factory=list)
    error_type: str | None = None

    def as_dict(self) -> dict:
        return {
            "state": self.state, "application": self.application,
            "order": self.order[:], "healthy": self.healthy[:],
            "degraded": self.degraded[:], "events": self.events[:],
            "compensated": self.compensated[:],
            "pending_undo": self.pending_undo[:],
            "rollback_errors": self.rollback_errors[:],
            "error_type": self.error_type,
            "production_activation_allowed": False,
        }


def _validated_plan(document: dict) -> tuple[dict, dict]:
    try:
        inspected = validate_v2(document)
    except (ManifestV2Error, TypeError, KeyError) as exc:
        raise OnboardingError("Invalid multi-service deployment manifest") from exc
    if document["deployment"]["strategy"] != "systemd":
        raise OnboardingError("V2-003 simulation currently supports systemd-only graphs")
    if document["application"]["kind"] in ("platform", "library"):
        raise OnboardingError("Protected platform and library releases are not eligible")
    if document.get("containers") or document.get("databases", []):
        raise OnboardingError("V2-003 does not simulate container or database state changes")
    if document.get("capabilities") or document.get("proxy", {}).get("routes"):
        # A service-only dry run must not look like full deployment acceptance.
        raise OnboardingError("Advanced host capabilities and proxy routes require separate adapters")
    if not document.get("health"):
        raise OnboardingError("V2-003 requires explicit aggregate health policy")
    if inspected.get("deployment_allowed") is not False:
        raise OnboardingError("V2 validation unexpectedly authorised deployment")
    services = {item["name"]: item for item in document["services"]}
    if set(inspected["deployment_order"]) != set(services):
        raise OnboardingError("Deployment plan does not cover all services")
    return inspected, services


def simulate_multiservice_release(
    document: dict, adapter: SimulationAdapter, *,
    journal: Callable[[dict], None],
    before_mutation: Callable[[dict[str, object]], None] | None = None,
    simulation_only: bool = False,
) -> MultiServiceResult:
    """Simulate transaction order, health aggregation and reverse compensation.

    No installation permissions are ever granted by this function. Callbacks
    must be supplied by the caller and are deliberately not bound to the
    production service control path. A journal callback is mandatory.
    """
    if simulation_only is not True or not callable(journal):
        raise OnboardingError("Multi-service simulation requires explicit simulation-only mode and journal")
    inspected, services = _validated_plan(document)
    result = MultiServiceResult(
        state="preparing", application=inspected["application"],
        order=inspected["deployment_order"][:],
    )
    optional = set(document["health"].get("optional_services", []))
    snapshots: dict[str, object] = {}
    # Record independently undoable operations, including partially completed.
    undo: list[tuple[str, str]] = []
    acquired = False
    journal_compromised = False

    def event(label: str) -> None:
        nonlocal journal_compromised
        # Only stage names and statuses, never commands/secrets/error text.
        result.events.append(label)
        try:
            journal(result.as_dict())
        except Exception:
            journal_compromised = True
            raise

    def register_undo(operation: str, name: str) -> None:
        marker = f"{operation}:{name}"
        undo.append((operation, name))
        result.pending_undo.append(marker)
        event("intent:" + marker)  # Persist before the effect.

    try:
        adapter.acquire_lock()
        acquired = True
        event("lock_acquired")
        # Snapshot ALL services before touching ANY of them.
        for name in result.order:
            snap = adapter.capture_snapshot(name)
            if snap is None:
                raise OnboardingError("Missing recovery snapshot for a service")
            snapshots[name] = snap
            event("snapshot:" + name)
        # The caller must durably persist all pre-mutation snapshots while
        # the adapter lock is held, before any configure/start callback.
        # On failure no service mutation is allowed.
        if before_mutation is not None:
            before_mutation(dict(snapshots))
            event("snapshots_persisted")
        result.state = "applying"
        event("preflight_complete")
        for name in result.order:
            register_undo("restore", name)
            adapter.configure(name, snapshots[name])
            event("configured:" + name)
        for name in result.order:
            register_undo("stop", name)
            adapter.start(name)
            event("started:" + name)
        for name in result.order:
            health_type = services[name].get("health", {}).get("type")
            healthy = bool(adapter.check_health(name, health_type))
            if not healthy:
                if name in optional:
                    result.degraded.append(name)
                    event("degraded:" + name)
                    continue
                raise OnboardingError(f"Required service {name} did not pass its health check")
            result.healthy.append(name)
            event("healthy:" + name)
        result.state = "degraded" if result.degraded else "healthy"
        event("complete")
    except Exception as exc:
        result.error_type = type(exc).__name__
        result.state = "rolling_back"
        try:
            event("rollback_started")
        except Exception:
            result.rollback_errors.append("journal")
        for operation, name in reversed(undo):
            marker = f"{operation}:{name}"
            try:
                if operation == "stop":
                    adapter.stop(name)
                else:
                    adapter.restore(name, snapshots[name])
                result.compensated.append(marker)
                result.pending_undo.remove(marker)
            except Exception:
                result.rollback_errors.append(marker)
            try:
                event("compensated:" + marker)
            except Exception:
                result.rollback_errors.append("journal")
        result.state = "rollback_failed" if result.rollback_errors or journal_compromised else "rolled_back"
        try:
            event("rollback_complete")
        except Exception:
            result.rollback_errors.append("journal")
            result.state = "rollback_failed"
    finally:
        if acquired:
            try:
                adapter.release_lock()
            except Exception:
                # Lock failure cannot be claimed as an accepted release.
                result.rollback_errors.append("lock_release")
                result.state = "rollback_failed"
    return result
