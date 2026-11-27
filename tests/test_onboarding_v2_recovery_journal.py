"""V2 recovery journal security and simulated crash-status tests (offline only)."""
from __future__ import annotations

import json
import uuid

import pytest
import yaml
from pathlib import Path

from onboarding import OnboardingError
from onboarding_v2_recovery_journal import DurableServiceJournal
from onboarding_v2_multiservice import simulate_multiservice_release

ROOT = Path(__file__).resolve().parents[1]


def transaction(tmp_path):
    return DurableServiceJournal(tmp_path / "private", str(uuid.uuid4()))


def record(state="applying", event="intent:stop:web", pending=None):
    return {"state": state, "events": [event],
            "pending_undo": ["stop:web"] if pending is None else pending,
            "environment": {"MAIL_PASSWORD": "must-not-log"},
            "entrypoint": ["sh", "-c", "secret"]}


def test_durable_chain_is_append_only_and_secret_free(tmp_path):
    journal = transaction(tmp_path)
    journal(record(event="snapshot:web", pending=[]))
    journal(record())
    entries = journal.records()
    assert len(entries) == 2
    assert entries[0]["digest"] == entries[1]["previous"]
    assert entries[0]["index"] == 0 and entries[1]["index"] == 1
    assert journal.path.stat().st_mode & 0o077 == 0
    assert journal.directory.stat().st_mode & 0o077 == 0
    blob = journal.path.read_text()
    assert "MAIL_PASSWORD" not in blob and "must-not-log" not in blob
    assert "entrypoint" not in blob and "secret" not in blob


def test_refuses_manifest_supplied_command_in_operation_name(tmp_path):
    journal = transaction(tmp_path)
    with pytest.raises(OnboardingError, match="allowlisted"):
        journal(record(event="started:web;rm -rf /"))
    assert not journal.path.exists()


def test_detects_modified_event_body(tmp_path):
    journal = transaction(tmp_path)
    journal(record(event="snapshot:web"))
    raw = journal.path.read_text()
    journal.path.write_text(raw.replace("snapshot:web", "snapshot:api"))
    with pytest.raises(OnboardingError, match="digest mismatch"):
        journal.records()


def test_detects_truncated_journal(tmp_path):
    journal = transaction(tmp_path)
    journal(record())
    journal.path.write_bytes(journal.path.read_bytes()[:-1])
    with pytest.raises(OnboardingError, match="incomplete"):
        journal.recovery_status()


def test_detects_missing_first_chain_link(tmp_path):
    journal = transaction(tmp_path)
    journal(record(event="snapshot:web"))
    journal(record())
    lines = journal.path.read_text().splitlines()
    journal.path.write_text(lines[1] + "\n")
    with pytest.raises(OnboardingError, match="ordering mismatch"):
        journal.records()


def test_detects_symlink_and_unsafe_permissions(tmp_path):
    journal = transaction(tmp_path)
    journal.path.symlink_to(tmp_path / "outside")
    with pytest.raises(OnboardingError, match="symlink"):
        journal(record())
    journal.path.unlink()
    journal(record())
    journal.path.chmod(0o644)
    with pytest.raises(OnboardingError, match="permissions"):
        journal.records()


def test_blocked_terminal_journal_reuse(tmp_path):
    journal = transaction(tmp_path)
    journal(record(state="healthy", event="complete", pending=[]))
    with pytest.raises(OnboardingError, match="Terminal"):
        journal(record(state="applying", event="configured:web"))


def test_recovery_is_review_only_for_unfinished_work(tmp_path):
    journal = transaction(tmp_path)
    journal(record(state="applying", event="intent:stop:web"))
    status = journal.recovery_status()
    assert status["status"] == "applying"
    assert status["pending_undo"] == ["stop:web"]
    assert status["manual_approval_required"] is True
    assert status["can_auto_replay"] is False


def test_private_root_required(tmp_path):
    path = tmp_path / "public"
    path.mkdir(mode=0o755)
    with pytest.raises(OnboardingError, match="unsafe permissions"):
        DurableServiceJournal(path, str(uuid.uuid4()))


def test_simulated_controller_can_write_recovery_events(tmp_path):
    document = yaml.safe_load((ROOT / "examples/uda-v2-multi-service.yaml").read_text())
    journal = transaction(tmp_path)

    class Fake:
        def __init__(self):
            self.snapshots = {"web": False, "mailbox": False}
            self.running = set()
        def acquire_lock(self): pass
        def release_lock(self): pass
        def capture_snapshot(self, name): return {"state": self.snapshots[name]}
        def configure(self, name, snapshot): pass
        def start(self, name): self.running.add(name)
        def check_health(self, name, health_type): return name == "web"
        def stop(self, name): self.running.discard(name)
        def restore(self, name, snapshot): pass

    result = simulate_multiservice_release(
        document, Fake(), journal=journal, simulation_only=True)
    assert result.state == "degraded"
    assert journal.recovery_status()["status"] == "degraded"
    assert journal.recovery_status()["manual_approval_required"] is False
    assert journal.recovery_status()["can_auto_replay"] is False
    assert len(journal.records()) > 10
