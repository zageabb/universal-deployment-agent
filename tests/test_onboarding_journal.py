"""Durable journal and rollback-error regression tests."""
import uuid

import pytest

from onboarding import OnboardingError
from onboarding_journal import FileJournal
from onboarding_transaction import execute_transaction


def test_journal_writes_private_append_only_events(tmp_path):
    ticket = str(uuid.uuid4())
    events = FileJournal(tmp_path / "journal", ticket)
    events({"transaction_id": ticket, "state": "preparing", "executed": [],
            "rolled_back": [], "error": None, "rollback_errors": []})
    events({"transaction_id": ticket, "state": "completed",
            "executed": ["verify_health"], "rolled_back": [],
            "error": None, "rollback_errors": []})
    assert [row["state"] for row in events.events()] == ["preparing", "completed"]
    assert events.path.stat().st_mode & 0o777 == 0o600


def test_journal_redacts_exception_messages(tmp_path):
    ticket = str(uuid.uuid4())
    journal = FileJournal(tmp_path / "audit", ticket)
    journal({"transaction_id": ticket, "state": "rollback_failed",
             "executed": [], "rolled_back": [],
             "error": "token=secret123", "rollback_errors": ["DATABASE_URL=secret"]})
    data = journal.path.read_text()
    assert "secret123" not in data
    assert "DATABASE_URL" not in data


def test_journal_rejects_unexpected_fields(tmp_path):
    ticket = str(uuid.uuid4())
    journal = FileJournal(tmp_path / "audit", ticket)
    with pytest.raises(OnboardingError, match="Unexpected"):
        journal({"transaction_id": ticket, "secret": "never"})


def test_journal_refuses_non_private_root(tmp_path):
    root = tmp_path / "public"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    with pytest.raises(OnboardingError, match="private"):
        FileJournal(root, str(uuid.uuid4()))


def test_failed_journal_during_compensation_does_not_stop_rollback():
    from test_onboarding_transaction import FakeAdapter, fixture
    plan, release = fixture()
    adapter = FakeAdapter(fail_at="publish_proxy")
    attempts = 0
    def journal(_):
        nonlocal attempts
        attempts += 1
        if attempts >= 8:
            raise OSError("audit drive full")
    result = execute_transaction(
        plan, release, adapter, transaction_id=str(uuid.uuid4()),
        explicitly_approved=True, production_enablement=True, journal=journal)
    assert result.state == "rollback_failed"
    assert "undo_service" in adapter.events
    assert adapter.locked is False
