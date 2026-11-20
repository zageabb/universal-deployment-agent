"""V2-003 offline worker acceptance rehearsal, never production activation.

Combines fresh source/runtime verification, a one-use out-of-band REVIEW token,
durable journal and temp-only unit adapter. Rehearsal always uses injected
fake lifecycle callbacks. A review token is NOT installation permission.

No dashboard route, systemctl, sudo, network calls, registry or Caddy writes.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable
import uuid

from onboarding import OnboardingError
from onboarding_v2_approval import review_attestation
from onboarding_v2_multiservice import simulate_multiservice_release
from onboarding_v2_recovery_journal import DurableServiceJournal, _id
from onboarding_v2_recovery_preflight import save_recovery_evidence, _private as private_snapshot_root
from onboarding_v2_unit_renderer import render_reviewed_units
from onboarding_v2_unit_sandbox import UnitSandboxAdapter, _private_sandbox
from uda_manifest_v2_validate import ManifestV2Error, validate as validate_v2


def _same_bundle(reviewed: dict, fresh: dict) -> None:
    """Reattest all unit bytes, runtime evidence and release SHA immediately."""
    if not isinstance(reviewed, dict) or not isinstance(fresh, dict):
        raise OnboardingError("Reviewed deployment bundle is missing")
    keys = ("application", "commit_sha", "order", "unit_hashes",
            "runtime_hashes", "bundle_sha256", "units", "status",
            "approval_required", "deployment_allowed")
    if any(reviewed.get(key) != fresh.get(key) for key in keys):
        raise OnboardingError("Reviewed deployment bundle differs from fresh source/runtime evidence")


def rehearse_reviewed_release(
    manifest: dict, reviewed_bundle: dict, *, release_path: Path,
    source_commit_sha: str, environment_files: dict[str, Path],
    approved_entrypoints: dict[str, tuple[str, ...]],
    expected_units: dict[str, str], runtime_profiles: dict[str, dict] | None,
    review_token: str, reviewer: str, trusted_review_key: bytes,
    review_receipts: Path, sandbox: Path, journal_root: Path,
    snapshot_root: Path,
    transaction_id: str, is_running: Callable[[str], bool],
    start_unit: Callable[[str], None], stop_unit: Callable[[str], None],
    health_probe: Callable[[str, str], bool],
    rehearsal_only: bool = False, now: int | None = None,
) -> dict:
    """Offline transactional rehearsal with no route to production host.

    Caller is responsible for independent reviewer identity and key custody.
    This method never treats the review receipt as an execution credential.
    All mutable unit files are confined to the temporary private sandbox.
    """
    if rehearsal_only is not True:
        raise OnboardingError("Worker activation is disabled; explicit rehearsal-only required")
    _id(transaction_id)  # Validate before joining a transaction-derived path.
    # Validate all directories before using the receipt: prevents burning a
    # one-time review token for an untrusted or unavailable sandbox.
    root = _private_sandbox(sandbox)
    journal_root = _private_sandbox(journal_root)
    snapshot_root = _private_sandbox(snapshot_root)
    locations = [root, journal_root, snapshot_root]
    if any(a == c or a.is_relative_to(c) or c.is_relative_to(a)
           for i, a in enumerate(locations) for c in locations[i + 1:]):
        raise OnboardingError("Journal, snapshots and unit sandbox must be separate")
    private_snapshot_root(snapshot_root)
    # Reject repeated transaction IDs before consuming a single-use review.
    if (snapshot_root / (transaction_id + ".json")).exists():
        raise OnboardingError("Recovery snapshot for transaction already exists")
    try:
        validate_v2(manifest)
    except (ManifestV2Error, KeyError, TypeError) as exc:
        raise OnboardingError("Invalid reviewed service manifest") from exc
    fresh = render_reviewed_units(
        manifest, release_path=release_path,
        source_commit_sha=source_commit_sha,
        environment_files=environment_files,
        approved_entrypoints=approved_entrypoints,
        expected_units=expected_units,
        runtime_profiles=runtime_profiles,
    )
    _same_bundle(reviewed_bundle, fresh)
    # Exactly one service name maps to each approved unit. No manifest-defined
    # arbitrary process callbacks are allowed to be installed here.
    services = {item["name"] for item in manifest["services"]}
    if set(expected_units) != services or set(expected_units.values()) != set(fresh["units"]):
        raise OnboardingError("Reviewed service inventory differs from worker allowlist")
    adapter = UnitSandboxAdapter(
        sandbox=root, unit_names=expected_units,
        rendered_units={name: fresh["units"][unit].encode("utf-8")
                        for name, unit in expected_units.items()},
        is_running=is_running, start_unit=start_unit,
        stop_unit=stop_unit, health_probe=health_probe,
    )
    # The journal must accept the transaction ID and private store before
    # consuming the review token; an invalid transaction is not a review.
    journal = DurableServiceJournal(journal_root, transaction_id)
    # Reviewing this exact bundle consumes a one-use attestation; it never
    # grants privileged execution permission.
    receipt = review_attestation(
        fresh, review_token, operator=reviewer, signing_key=trusted_review_key,
        receipt_store=review_receipts, now=now,
    )
    if receipt["can_install"] is not False or receipt["permission"] != "review_only":
        raise OnboardingError("Review attestation unexpectedly enabled installation")
    def persist_snapshots(captured: dict[str, object]) -> None:
        # This callback is invoked after ALL unit snapshots and under the
        # coordinator lock, but BEFORE configure/start mutates anything.
        evidence = {}
        for service, unit in expected_units.items():
            snap = captured[service]
            if not isinstance(snap, dict) or snap.get("name") != service:
                raise OnboardingError("Incorrect captured service snapshot")
            evidence[unit] = {"bytes": snap["bytes"], "running": snap["running"]}
        save_recovery_evidence(snapshot_root, transaction_id, fresh,
                               evidence, expected_units)

    result = simulate_multiservice_release(
        manifest, adapter, journal=journal,
        before_mutation=persist_snapshots, simulation_only=True,
    )
    return {
        "mode": "offline_rehearsal",
        "application": fresh["application"],
        "source_commit": fresh["commit_sha"],
        "bundle_sha256": fresh["bundle_sha256"],
        "transaction_id": transaction_id,
        "service_result": result.as_dict(),
        "journal": journal.recovery_status(),
        "snapshot_persisted": (snapshot_root / (transaction_id + ".json")).is_file(),
        "review_permission": receipt["permission"],
        "host_changes_allowed": False,
        "production_activation_allowed": False,
    }
