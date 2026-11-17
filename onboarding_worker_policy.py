"""Fail-closed recovery authorization and worker capability policy.

This module is data-only. The standard dashboard must never be able to grant
production worker capability by setting a manifest flag.
"""
from __future__ import annotations

from pathlib import Path
import os
import stat
import uuid

from onboarding import OnboardingError


def recovery_decision(record: dict, *, operator_id: str, ticket_transaction_id: str,
                      approval_file: Path | None = None) -> dict:
    """Accept only a transaction-specific operator approval file (not repo data).

    This validates metadata and permissions only. A trusted service manager
    must authenticate the operator and verify the file was created by its own
    approval process; this method alone never authorizes host mutation.
    """
    if not isinstance(operator_id, str) or not operator_id.strip() or len(operator_id) > 128:
        raise OnboardingError("Missing authenticated operator")
    try:
        tid = str(uuid.UUID(ticket_transaction_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise OnboardingError("Invalid recovery approval identity") from exc
    if record.get("transaction_id") != tid:
        raise OnboardingError("Recovery approval is for a different transaction")
    if not record.get("pending_undo"):
        raise OnboardingError("No outstanding recovery operations")
    if approval_file is None:
        raise OnboardingError("Trusted out-of-band approval is required")
    if approval_file.is_symlink() or not approval_file.is_file():
        raise OnboardingError("Trusted approval file missing or linked")
    mode = approval_file.stat().st_mode
    if mode & 0o077:
        raise OnboardingError("Approval file must be private")
    # The authorization service must provide the separately authenticated
    # identity, token binding, expiry and one-time-use enforcement.
    return {"transaction_id": tid, "operator": operator_id,
            "approval_file": str(approval_file), "permission": "review_only",
            "can_execute": False}


def worker_capabilities(config: dict) -> dict:
    """No remote manifest or dashboard flag can turn on the privileged worker."""
    return {"production_activation": False,
            "automatic_crash_recovery": False,
            "manual_recovery_requested": bool(config.get("manual_recovery_requested", False)),
            "operator_approval_required": True,
            "worker_integration": "not_installed"}
