"""Recovery worker must remain disabled without trusted integration."""
import uuid
import pytest

from onboarding import OnboardingError
from onboarding_worker_policy import recovery_decision, worker_capabilities


def test_untrusted_configuration_never_enables_worker():
    flags = worker_capabilities({"production_activation": True,
                                 "automatic_crash_recovery": True})
    assert flags["production_activation"] is False
    assert flags["automatic_crash_recovery"] is False


def test_recovery_requires_out_of_band_approval(tmp_path):
    tid = str(uuid.uuid4())
    record = {"transaction_id": tid, "pending_undo": ["service"]}
    with pytest.raises(OnboardingError, match="out-of-band"):
        recovery_decision(record, operator_id="admin", ticket_transaction_id=tid)


def test_recovery_review_does_not_grant_execution(tmp_path):
    tid = str(uuid.uuid4())
    approval = tmp_path / "approval"
    approval.write_text("out-of-band placeholder")
    approval.chmod(0o600)
    result = recovery_decision(
        {"transaction_id": tid, "pending_undo": ["service"]},
        operator_id="admin", ticket_transaction_id=tid, approval_file=approval)
    assert result["permission"] == "review_only"
    assert result["can_execute"] is False


def test_wrong_transaction_cannot_use_approval(tmp_path):
    approval = tmp_path / "approval"
    approval.write_text("placeholder")
    approval.chmod(0o600)
    with pytest.raises(OnboardingError, match="different transaction"):
        recovery_decision({"transaction_id": str(uuid.uuid4()),
                           "pending_undo": ["proxy"]},
                          operator_id="admin", ticket_transaction_id=str(uuid.uuid4()),
                          approval_file=approval)
