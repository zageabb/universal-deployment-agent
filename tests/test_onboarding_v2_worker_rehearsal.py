"""V2-003 offline worker chain: read-only approval + isolated rollback.

No real systemd or Ubuntu service actions are invoked. All startup/health
callbacks are deterministic fakes. Both output and journal deny activation.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import uuid

import pytest
import yaml

from onboarding import OnboardingError
from onboarding_release import prepare_release
from onboarding_v2_approval import issue_review_attestation
from onboarding_v2_unit_renderer import render_reviewed_units
from onboarding_v2_worker_rehearsal import rehearse_reviewed_release

SHA = "a" * 40
KEY = b"independent-v2-test-authority-key-1234567"
ROOT = Path(__file__).resolve().parents[1]


def setup(tmp_path, *, unhealthy=(), fail_on=None, old_active=()):
    staging = tmp_path / "staging"
    staging.mkdir()
    source = staging / ("tender-designer-" + SHA[:12])
    source.mkdir()
    (source / "app.py").write_text("pass\n")
    (source / "mailbox_daemon.py").write_text("pass\n")
    releases = tmp_path / "releases"
    releases.mkdir()
    release = prepare_release({
        "application": "tender-designer", "repository": "zageabb/tender_designer",
        "commit_sha": SHA, "staged_path": str(source),
    }, staging, releases)
    doc = yaml.safe_load((ROOT / "examples/uda-v2-multi-service.yaml").read_text())
    units = {"web": "tender-web.service", "mailbox": "tender-mailbox.service"}
    commands = {"web": ("/usr/bin/python3", "app.py"),
                "mailbox": ("/usr/bin/python3", "mailbox_daemon.py")}
    for service in doc["services"]:
        service["systemd_unit"] = units[service["name"]]
        service["entrypoint"] = list(commands[service["name"]])
    env = {}
    for name in units:
        file = tmp_path / (name + ".env")
        file.write_text("SECRET=should-not-be-saved\n")
        file.chmod(0o600)
        env[name] = file
    unit_root = tmp_path / "sandbox"
    unit_root.mkdir(mode=0o700)
    (unit_root / "units").mkdir(mode=0o700)
    originals = {}
    for name, unit in units.items():
        content = ("prior-unit-" + name).encode()
        (unit_root / "units" / unit).write_bytes(content)
        originals[name] = content
    journal_root = tmp_path / "audit"
    journal_root.mkdir(mode=0o700)
    receipts = tmp_path / "receipts"
    receipts.mkdir(mode=0o700)
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir(mode=0o700)
    bundle = render_reviewed_units(
        doc, release_path=Path(release["release_path"]),
        source_commit_sha=SHA, environment_files=env,
        approved_entrypoints=commands, expected_units=units,
    )
    token = issue_review_attestation(
        bundle, operator="reviewer@example.com", signing_key=KEY,
        now=20000, nonce="b" * 32,
    )
    running = set(old_active)
    calls = []

    def record(action, name):
        calls.append(action + ":" + name)
        if action + ":" + name == fail_on:
            raise RuntimeError("injected worker failure")

    def start(name):
        running.add(name)
        record("start", name)

    def stop(name):
        running.discard(name)
        record("stop", name)

    def health(name, kind):
        record("health", name)
        return name not in unhealthy

    args = dict(
        manifest=doc, reviewed_bundle=bundle,
        release_path=Path(release["release_path"]), source_commit_sha=SHA,
        environment_files=env, approved_entrypoints=commands,
        expected_units=units, runtime_profiles=None,
        review_token=token, reviewer="reviewer@example.com",
        trusted_review_key=KEY, review_receipts=receipts,
        sandbox=unit_root, journal_root=journal_root,
        snapshot_root=snapshot_root,
        transaction_id=str(uuid.uuid4()),
        is_running=lambda name: name in running,
        start_unit=start, stop_unit=stop, health_probe=health,
        rehearsal_only=True, now=20001,
    )
    return args, originals, running, calls


def run(args):
    return rehearse_reviewed_release(**args)


def test_complete_transaction_requires_review_and_writes_only_sandbox(tmp_path):
    args, before, running, calls = setup(tmp_path)
    result = run(args)
    assert result["mode"] == "offline_rehearsal"
    assert result["service_result"]["state"] == "healthy"
    assert result["review_permission"] == "review_only"
    assert result["production_activation_allowed"] is False
    assert result["host_changes_allowed"] is False
    assert running == {"web", "mailbox"}
    assert calls.index("start:web") < calls.index("start:mailbox")
    for name, unit in args["expected_units"].items():
        assert (args["sandbox"] / "units" / unit).read_bytes() == (
            args["reviewed_bundle"]["units"][unit].encode())
    assert result["journal"]["status"] == "healthy"
    assert len(list(args["review_receipts"].iterdir())) == 1
    assert not (tmp_path / "Caddyfile").exists()
    assert not (tmp_path / "registry.json").exists()


def test_failure_restores_all_prior_file_bytes_and_running_states(tmp_path):
    args, before, running, calls = setup(tmp_path, unhealthy={"web"},
                                          old_active={"web"})
    result = run(args)
    assert result["service_result"]["state"] == "rolled_back"
    assert result["journal"]["status"] == "rolled_back"
    assert running == {"web"}
    for name, unit in args["expected_units"].items():
        assert (args["sandbox"] / "units" / unit).read_bytes() == before[name]
    assert "stop:mailbox" in calls


def test_optional_worker_failure_is_degraded_not_healthy(tmp_path):
    args, _, _, _ = setup(tmp_path, unhealthy={"mailbox"})
    result = run(args)
    assert result["service_result"]["state"] == "degraded"
    assert result["service_result"]["degraded"] == ["mailbox"]


def test_rehearsal_disabled_without_trusted_explicit_flag(tmp_path):
    args, before, running, calls = setup(tmp_path)
    args["rehearsal_only"] = False
    with pytest.raises(OnboardingError, match="disabled"):
        run(args)
    assert not calls and not list(args["review_receipts"].iterdir())
    assert running == set()


def test_changed_bundle_fails_before_receipt_or_mutation(tmp_path):
    args, before, running, calls = setup(tmp_path)
    changed = deepcopy(args["reviewed_bundle"])
    changed["units"]["tender-web.service"] += "\nEnvironment=EVIL=1\n"
    args["reviewed_bundle"] = changed
    with pytest.raises(OnboardingError, match="differs"):
        run(args)
    assert not calls and not list(args["review_receipts"].iterdir())


def test_modified_release_fails_before_receipt_or_mutation(tmp_path):
    args, before, running, calls = setup(tmp_path)
    (args["release_path"] / "app.py").write_text("altered\n")
    with pytest.raises(OnboardingError, match="checksum"):
        run(args)
    assert not calls and not list(args["review_receipts"].iterdir())


def test_wrong_reviewer_fails_closed_before_mutation(tmp_path):
    args, before, running, calls = setup(tmp_path)
    args["reviewer"] = "another@example.com"
    with pytest.raises(OnboardingError, match="scope differs"):
        run(args)
    assert not calls and not list(args["review_receipts"].iterdir())


def test_one_use_receipt_blocks_replay_before_second_service_mutation(tmp_path):
    args, before, running, calls = setup(tmp_path)
    run(args)
    n = len(calls)
    args["transaction_id"] = str(uuid.uuid4())
    with pytest.raises(OnboardingError, match="already been consumed"):
        run(args)
    assert len(calls) == n


def test_extra_worker_in_inventory_fails_before_receipt(tmp_path):
    args, before, running, calls = setup(tmp_path)
    args["expected_units"] = {**args["expected_units"], "intruder": "rogue.service"}
    with pytest.raises(OnboardingError):
        run(args)
    assert not calls and not list(args["review_receipts"].iterdir())


def test_unsafe_journal_location_not_allowed(tmp_path):
    args, before, running, calls = setup(tmp_path)
    args["journal_root"] = args["sandbox"]
    with pytest.raises(OnboardingError, match="separate"):
        run(args)
    assert not calls and not list(args["review_receipts"].iterdir())


def test_journal_records_only_allowlisted_state_and_no_env_secrets(tmp_path):
    args, before, running, calls = setup(tmp_path)
    result = run(args)
    events = (args["journal_root"] / (result["transaction_id"] + ".jsonl")).read_text()
    assert "should-not-be-saved" not in events
    assert "ExecStart" not in events
    assert "SECRET=" not in events
    assert result["service_result"]["production_activation_allowed"] is False


def test_invalid_transaction_identity_does_not_consume_review_token(tmp_path):
    args, before, running, calls = setup(tmp_path)
    args["transaction_id"] = "../invalid"
    with pytest.raises(OnboardingError, match="transaction ID"):
        run(args)
    assert not calls
    assert not list(args["review_receipts"].iterdir())
    assert not list(args["journal_root"].iterdir())


def test_snapshot_evidence_precedes_any_unit_configuration(tmp_path):
    from onboarding_v2_recovery_preflight import _load
    args, before, running, calls = setup(tmp_path, old_active={"web"})
    original_start = args["start_unit"]
    def checked_start(name):
        snapshot = _load(args["snapshot_root"], args["transaction_id"])
        assert set(snapshot["units"]) == set(args["expected_units"].values())
        assert snapshot["units"][args["expected_units"]["web"]]["running"] is True
        original_start(name)
    args["start_unit"] = checked_start
    result = run(args)
    assert result["snapshot_persisted"] is True
    event_data = (args["journal_root"] / (args["transaction_id"] + ".jsonl")).read_text()
    assert event_data.index("snapshots_persisted") < event_data.index("intent:restore:web")
    assert result["service_result"]["state"] == "healthy"


def test_invalid_snapshot_directory_blocks_review_consumption(tmp_path):
    args, before, running, calls = setup(tmp_path)
    args["snapshot_root"].chmod(0o755)
    with pytest.raises(OnboardingError, match="private"):
        run(args)
    assert not calls and not list(args["review_receipts"].iterdir())


def test_duplicate_snapshot_transaction_id_blocks_review_consumption(tmp_path):
    args, before, running, calls = setup(tmp_path)
    txn = args["transaction_id"]
    (args["snapshot_root"] / (txn + ".json")).write_text("existing evidence")
    with pytest.raises(OnboardingError, match="already exists"):
        run(args)
    assert not calls and not list(args["review_receipts"].iterdir())


def test_failed_snapshot_persistence_does_not_mutate_services(tmp_path):
    args, before, running, calls = setup(tmp_path)
    # After the receipt is consumed, sabotage only the evidence directory.
    # Journal events are still durable; the coordinator must not mutate.
    from onboarding_v2_unit_sandbox import UnitSandboxAdapter
    original = UnitSandboxAdapter.capture_snapshot
    def make_readonly(self, name):
        snap = original(self, name)
        args["snapshot_root"].chmod(0o755)
        return snap
    from unittest.mock import patch
    with patch.object(UnitSandboxAdapter, "capture_snapshot", make_readonly):
        outcome = run(args)
    assert outcome["service_result"]["state"] == "rolled_back"
    assert outcome["snapshot_persisted"] is False
    assert all((args["sandbox"] / "units" / unit).read_bytes() == before[name]
               for name, unit in args["expected_units"].items())
    assert calls == []
