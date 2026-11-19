"""Offline persistence and explicit crash compensation tests."""
import json
from pathlib import Path
import uuid

import pytest

from onboarding import OnboardingError
from onboarding_recovery import (
    save_snapshot, load_snapshot, inspect_incomplete, replay_compensations,
)
from onboarding_journal import FileJournal


def ident():
    return str(uuid.uuid4())


def snapshot(token):
    return {"transaction_id": token,
            "registry": b'{"dashboard_token":"private"}',
            "unit": None, "proxy": b"before-proxy", "attestation": None}


def test_snapshot_created_private_and_exact(tmp_path):
    transaction_id = ident()
    root = tmp_path / "snapshots"
    path = save_snapshot(root, transaction_id, snapshot(transaction_id))
    assert path.stat().st_mode & 0o777 == 0o600
    assert root.stat().st_mode & 0o777 == 0o700
    assert load_snapshot(root, transaction_id) == snapshot(transaction_id)


def test_cannot_overwrite_existing_snapshot(tmp_path):
    transaction_id = ident()
    save_snapshot(tmp_path, transaction_id, snapshot(transaction_id))
    with pytest.raises(FileExistsError):
        save_snapshot(tmp_path, transaction_id, snapshot(transaction_id))


def test_reject_exposed_snapshot_and_wrong_id(tmp_path):
    first, second = ident(), ident()
    path = save_snapshot(tmp_path, first, snapshot(first))
    with pytest.raises(OnboardingError, match="missing"):
        load_snapshot(tmp_path, second)
    path.chmod(0o644)
    with pytest.raises(OnboardingError, match="exposed"):
        load_snapshot(tmp_path, first)


def test_recovery_discovers_in_progress_but_does_not_act(tmp_path):
    transaction_id = ident()
    journal = FileJournal(tmp_path / "journals", transaction_id)
    journal({"transaction_id": transaction_id, "state": "applying",
             "pending_undo": ["service", "start", "registry"],
             "executed": ["configure_service", "start_service"],
             "rolled_back": [], "error": None, "rollback_errors": []})
    found = inspect_incomplete(tmp_path / "journals")
    assert len(found) == 1
    assert found[0]["pending_undo"] == ["service", "start", "registry"]
    assert found[0]["requires_manual_approval"] is True


class FakeAdapter:
    def __init__(self, fail=None):
        self.events = []
        self.locked = False
        self.fail = fail

    def acquire_lock(self):
        self.locked = True
    def release_lock(self):
        self.locked = False
    def compensate(self, step, state, plan):
        self.events.append(step)
        if step == self.fail:
            raise RuntimeError("refused")


def test_recovery_refuses_automatic_replay(tmp_path):
    transaction_id = ident()
    adapter = FakeAdapter()
    with pytest.raises(OnboardingError, match="approval"):
        replay_compensations(snapshot(transaction_id),
                             {"transaction_id": transaction_id, "state": "applying",
                              "pending_undo": ["service"]}, {}, adapter)
    assert adapter.events == []


def test_manual_recovery_replays_in_reverse_order(tmp_path):
    transaction_id = ident()
    adapter = FakeAdapter()
    result = replay_compensations(snapshot(transaction_id),
        {"transaction_id": transaction_id, "state": "applying",
         "pending_undo": ["service", "start", "registry", "proxy"]},
         {"application": "demo"}, adapter, explicitly_approved=True)
    assert result["state"] == "rolled_back"
    assert adapter.events == ["proxy", "registry", "start", "service"]
    assert adapter.locked is False


def test_partial_failure_is_not_false_success(tmp_path):
    transaction_id = ident()
    adapter = FakeAdapter(fail="registry")
    result = replay_compensations(snapshot(transaction_id),
        {"transaction_id": transaction_id, "state": "applying",
         "pending_undo": ["service", "registry", "proxy"]},
         {}, adapter, explicitly_approved=True)
    assert result["state"] == "rollback_failed"
    assert result["failed"] == ["registry"]
    assert adapter.events == ["proxy", "registry", "service"]
    assert adapter.locked is False


def test_failed_or_terminal_journal_is_not_replayed(tmp_path):
    transaction_id = ident()
    adapter = FakeAdapter()
    with pytest.raises(OnboardingError, match="already terminal"):
        replay_compensations(snapshot(transaction_id),
            {"transaction_id": transaction_id, "state": "completed",
             "pending_undo": ["service"]}, {}, adapter, explicitly_approved=True)
