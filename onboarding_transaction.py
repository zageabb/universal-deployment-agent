"""Explicitly gated installation transaction with compensating operations.

The controller has no systemd, Caddy, filesystem or network implementation.
A separate privileged adapter and integration acceptance are mandatory before
it can alter a production host. No dashboard route calls this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from onboarding import OnboardingError


class InstallAdapter(Protocol):
    """Contract for a future independently audited Ubuntu-only worker.

    All mutating methods must either be atomic or idempotently undoable even if
    an exception occurs after partial mutation.
    """
    def acquire_lock(self) -> None: ...
    def release_lock(self) -> None: ...
    def capture_snapshot(self, transaction_id: str) -> object: ...
    def preflight(self, plan: dict, release: dict) -> None: ...
    def configure_service(self, plan: dict, release: dict) -> None: ...
    def start_service(self, plan: dict) -> None: ...
    def verify_health(self, plan: dict, release: dict) -> None: ...
    def register_application(self, plan: dict, release: dict) -> None: ...
    def publish_proxy(self, plan: dict) -> None: ...
    def verify_authentication(self, plan: dict) -> None: ...
    def verify_runtime_sha(self, plan: dict, release: dict) -> None: ...
    def record_attestation(self, plan: dict, release: dict) -> None: ...
    def compensate(self, step: str, snapshot: object, plan: dict) -> None: ...


STEPS = (
    ("configure_service", "service"),
    ("start_service", "start"),
    ("verify_health", None),
    ("register_application", "registry"),
    ("publish_proxy", "proxy"),
    ("verify_authentication", None),
    ("verify_runtime_sha", None),
    ("record_attestation", "attestation"),
)


@dataclass
class TransactionResult:
    transaction_id: str
    state: str
    executed: list[str] = field(default_factory=list)
    rolled_back: list[str] = field(default_factory=list)
    error: str | None = None
    rollback_errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "transaction_id": self.transaction_id, "state": self.state,
            "executed": self.executed[:], "rolled_back": self.rolled_back[:],
            "error": self.error, "rollback_errors": self.rollback_errors[:],
        }


def execute_transaction(plan: dict, release: dict, adapter: InstallAdapter, *,
                        transaction_id: str, explicitly_approved: bool = False,
                        production_enablement: bool = False,
                        journal: Callable[[dict], None] | None = None) -> TransactionResult:
    """Execute only with a separately supplied, privilege-restricted adapter.

    No production adapter is supplied in this repository. Both approval flags
    must be explicitly set by a trusted caller, not a repository manifest.
    """
    if not explicitly_approved or not production_enablement:
        raise OnboardingError("Activation disabled pending separate trusted approval")
    if (not isinstance(transaction_id, str) or
            len(transaction_id) != 36 or
            any(ch not in "0123456789abcdef-" for ch in transaction_id)):
        raise OnboardingError("Invalid transaction identifier")
    if plan.get("application") != release.get("application") or plan.get("commit_sha") != release.get("commit_sha"):
        raise OnboardingError("Activation identity mismatch")
    if plan.get("stage_only") is not True or release.get("status") != "prepared_inactive":
        raise OnboardingError("Unreviewed release is not eligible for activation")

    result = TransactionResult(transaction_id=transaction_id, state="preparing")
    lock_acquired = False
    snapshot = None
    undo: list[str] = []

    def write_journal(*, during_rollback: bool = False) -> None:
        if journal is not None:
            # Journal must durably commit before allowing each mutation.
            try:
                journal(result.as_dict())
            except Exception as journal_exc:
                if not during_rollback:
                    raise
                result.rollback_errors.append(
                    f"journal: {type(journal_exc).__name__}: {journal_exc}"
                )

    try:
        adapter.acquire_lock()
        lock_acquired = True
        snapshot = adapter.capture_snapshot(transaction_id)
        if snapshot is None:
            raise OnboardingError("No recovery snapshot available")
        adapter.preflight(plan, release)
        result.state = "applying"
        write_journal()
        for operation, compensation in STEPS:
            # Register compensation BEFORE side effects to cover partial success.
            if compensation is not None:
                undo.append(compensation)
            write_journal()
            getattr(adapter, operation)(plan, release) if operation in {
                "configure_service", "verify_health", "register_application",
                "verify_runtime_sha", "record_attestation"
            } else getattr(adapter, operation)(plan)
            result.executed.append(operation)
            write_journal()
        result.state = "completed"
        write_journal()
        return result
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.state = "rolling_back"
        if snapshot is not None:
            for step in reversed(undo):
                try:
                    # Never rollback another application's state; the adapter
                    # must enforce transaction-scoped snapshots.
                    adapter.compensate(step, snapshot, plan)
                    result.rolled_back.append(step)
                except Exception as rollback_exc:
                    result.rollback_errors.append(f"{step}: {type(rollback_exc).__name__}: {rollback_exc}")
                finally:
                    write_journal(during_rollback=True)
        result.state = "rollback_failed" if result.rollback_errors else "rolled_back"
        write_journal(during_rollback=True)
        return result
    finally:
        if lock_acquired:
            adapter.release_lock()


def delivery_after_activation(result: TransactionResult, publish: Callable[[], object]) -> dict:
    """Publish GitHub deployment only after verified activation.

    External reporting failures are recorded as delivery errors and do not
    roll back a healthy, already activated service.
    """
    if result.state != "completed":
        raise OnboardingError("Cannot report an uncommitted activation")
    try:
        publication = publish()
        return {"deployment": "completed", "github": "published", "publication": publication}
    except Exception as exc:
        return {"deployment": "completed", "github": "delivery_failed",
                "error": f"{type(exc).__name__}: {exc}"}
