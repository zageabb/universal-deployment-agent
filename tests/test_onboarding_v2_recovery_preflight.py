"""Read-only recovery preflight: no host actions or automatic replay."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid

import pytest

from onboarding import OnboardingError
from onboarding_v2_recovery_journal import DurableServiceJournal
from onboarding_v2_recovery_preflight import (
    save_recovery_evidence, plan_interrupted_recovery,
)

UNITS = {"web": "uda-test-web.service", "mailbox": "uda-test-mailbox.service"}


def bundle():
    files = {
        "uda-test-web.service": "[Service]\nExecStart=/usr/bin/true\n",
        "uda-test-mailbox.service": "[Service]\nExecStart=/usr/bin/true\n",
    }
    hashes = {name: hashlib.sha256(text.encode()).hexdigest()
              for name, text in files.items()}
    core = {"application": "tender-designer", "commit_sha": "a" * 40,
            "order": list(files), "unit_hashes": hashes}
    digest = hashlib.sha256(json.dumps(
        core, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
    return {**core, "units": files, "bundle_sha256": digest,
            "approval_required": True, "deployment_allowed": False,
            "status": "review_only"}


def setup(tmp_path):
    transaction = str(uuid.uuid4())
    snapshot = tmp_path / "snapshots"
    journal_root = tmp_path / "journal"
    snapshot.mkdir(mode=0o700)
    journal_root.mkdir(mode=0o700)
    old = {UNITS["web"]: {"bytes": b"prior-web", "running": True},
           UNITS["mailbox"]: {"bytes": None, "running": False}}
    plan = bundle()
    save_recovery_evidence(snapshot, transaction, plan, old, UNITS)
    journal = DurableServiceJournal(journal_root, transaction)
    return plan, transaction, snapshot, journal_root, journal


def record(journal, state, event, pending=None):
    journal({"state": state, "events": [event], "pending_undo": pending or []})


def read(plan, txn, snap, journal):
    return plan_interrupted_recovery(snapshot_root=snap,
        journal_root=journal, transaction_id=txn,
        reviewed_bundle=plan, service_units=UNITS)


def test_interrupted_transaction_needs_operator_and_orders_reverse_undo(tmp_path):
    plan, txn, snap, root, journal = setup(tmp_path)
    record(journal, "preparing", "snapshot:web")
    record(journal, "applying", "intent:restore:web", ["restore:web"])
    record(journal, "applying", "intent:restore:mailbox",
           ["restore:web", "restore:mailbox"])
    record(journal, "applying", "intent:stop:web",
           ["restore:web", "restore:mailbox", "stop:web"])
    result = read(plan, txn, snap, root)
    assert result["state"] == "review_required"
    assert result["pending_compensations"] == [
        {"operation": "stop", "service": "web", "unit": UNITS["web"]},
        {"operation": "restore", "service": "mailbox", "unit": UNITS["mailbox"]},
        {"operation": "restore", "service": "web", "unit": UNITS["web"]},
    ]
    assert result["prior_unit_states"] == {
        UNITS["web"]: True, UNITS["mailbox"]: False,
    }
    assert result["requires_operator_review"]
    assert not result["automatic_replay_allowed"] and not result["can_execute"]


def test_terminal_healthy_cannot_recover(tmp_path):
    plan, txn, snap, root, journal = setup(tmp_path)
    record(journal, "healthy", "complete")
    result = read(plan, txn, snap, root)
    assert result["state"] == "terminal"
    assert result["pending_compensations"] == []


def test_changed_bundle_is_rejected(tmp_path):
    plan, txn, snap, root, journal = setup(tmp_path)
    record(journal, "applying", "intent:stop:web", ["stop:web"])
    changed = {**plan, "commit_sha": "b" * 40}
    with pytest.raises(OnboardingError, match="digest"):
        read(changed, txn, snap, root)


def test_snapshot_tampering_is_rejected(tmp_path):
    plan, txn, snap, root, journal = setup(tmp_path)
    record(journal, "applying", "intent:stop:web", ["stop:web"])
    location = snap / (txn + ".json")
    data = location.read_text()
    location.write_text(data.replace("prior", "later"))
    with pytest.raises(OnboardingError, match="integrity"):
        read(plan, txn, snap, root)


def test_journal_tamper_is_rejected(tmp_path):
    plan, txn, snap, root, journal = setup(tmp_path)
    record(journal, "applying", "intent:stop:web", ["stop:web"])
    journal.path.write_text(journal.path.read_text().replace("stop:web", "stop:api"))
    with pytest.raises(OnboardingError):
        read(plan, txn, snap, root)


def test_missing_intent_rejects_pending_operation(tmp_path):
    plan, txn, snap, root, journal = setup(tmp_path)
    record(journal, "applying", "started:web", ["stop:web"])
    with pytest.raises(OnboardingError, match="intents"):
        read(plan, txn, snap, root)


def test_unknown_service_does_not_invent_unit_name(tmp_path):
    plan, txn, snap, root, journal = setup(tmp_path)
    record(journal, "applying", "intent:stop:other", ["stop:other"])
    with pytest.raises(OnboardingError, match="allowlist"):
        read(plan, txn, snap, root)


def test_cross_transaction_snapshot_not_accepted(tmp_path):
    plan, txn, snap, root, journal = setup(tmp_path)
    record(journal, "applying", "intent:stop:web", ["stop:web"])
    with pytest.raises(OnboardingError, match="missing"):
        read(plan, str(uuid.uuid4()), snap, root)


def test_repeated_snapshot_creation_fails_closed(tmp_path):
    plan, txn, snap, root, journal = setup(tmp_path)
    with pytest.raises(OnboardingError, match="already exists"):
        save_recovery_evidence(snap, txn, plan,
            {UNITS["web"]: {"bytes": b"x", "running": True},
             UNITS["mailbox"]: {"bytes": None, "running": False}}, UNITS)


def test_exposed_directory_and_symlink_refused(tmp_path):
    plan, txn, snap, root, journal = setup(tmp_path)
    snap.chmod(0o755)
    with pytest.raises(OnboardingError, match="private"):
        read(plan, txn, snap, root)
    snap.chmod(0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(snap, target_is_directory=True)
    with pytest.raises(OnboardingError, match="private absolute"):
        save_recovery_evidence(alias, str(uuid.uuid4()), plan,
            {UNITS["web"]: {"bytes": b"old", "running": True},
             UNITS["mailbox"]: {"bytes": None, "running": False}}, UNITS)


def test_mapping_drift_rejected_before_any_recovery(tmp_path):
    plan, txn, snap, root, journal = setup(tmp_path)
    record(journal, "applying", "intent:stop:web", ["stop:web"])
    swapped = {"web": UNITS["mailbox"], "mailbox": UNITS["web"]}
    with pytest.raises(OnboardingError, match="transaction"):
        plan_interrupted_recovery(snapshot_root=snap, journal_root=root,
            transaction_id=txn, reviewed_bundle=plan, service_units=swapped)
