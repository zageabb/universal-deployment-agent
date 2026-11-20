"""V2 interrupted deployment: actual process death, disk evidence and restart.

Tests are temp-dir-only and never invoke real services, systemctl or a live
deployment worker. SIGKILL is delivered to an isolated Python child process.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import uuid

import pytest
import yaml

from onboarding_v2_recovery_journal import DurableServiceJournal
from onboarding_v2_recovery_preflight import plan_interrupted_recovery

ROOT = Path(__file__).resolve().parents[1]
CHILD = ROOT / "tests" / "fixtures" / "v2_crash_child.py"
NAMES = {"web": "uda-test-web.service", "mailbox": "uda-test-mailbox.service"}


def _bundle():
    files = {unit: "[Service]\nExecStart=/usr/bin/true\n"
             for unit in NAMES.values()}
    hashes = {unit: hashlib.sha256(text.encode()).hexdigest()
              for unit, text in files.items()}
    evidence = {"application": "tender-designer", "commit_sha": "a" * 40,
                "order": list(files), "unit_hashes": hashes}
    digest = hashlib.sha256(json.dumps(
        evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**evidence, "bundle_sha256": digest, "units": files,
            "approval_required": True, "deployment_allowed": False,
            "status": "review_only"}


def _prepare(tmp_path, mode):
    sandbox = tmp_path / "sandbox"
    journal_root = tmp_path / "journal"
    snapshots = tmp_path / "snapshots"
    for root in (sandbox, journal_root, snapshots):
        root.mkdir(mode=0o700)
    unit_dir = sandbox / "units"
    unit_dir.mkdir(mode=0o700)
    original = {}
    for name, unit in NAMES.items():
        original[unit] = ("previous-" + name).encode()
        (unit_dir / unit).write_bytes(original[unit])
    manifest = yaml.safe_load((ROOT / "examples/uda-v2-multi-service.yaml").read_text())
    bundle = _bundle()
    txn = str(uuid.uuid4())
    for path, payload in (
        (tmp_path / "bundle.json", bundle),
        (tmp_path / "manifest.json", manifest),
    ):
        path.write_text(json.dumps(payload))
    config = {
        "sandbox": str(sandbox),
        "journal_root": str(journal_root),
        "snapshot_root": str(snapshots),
        "bundle_file": str(tmp_path / "bundle.json"),
        "manifest_file": str(tmp_path / "manifest.json"),
        "transaction_id": txn,
        "service_units": NAMES,
        "mode": mode,
    }
    control = tmp_path / "control.json"
    control.write_text(json.dumps(config))
    return config, control, bundle, original


def _kill_child(control):
    result = subprocess.run([sys.executable, str(CHILD), str(control)],
                            cwd=ROOT, capture_output=True, text=True,
                            timeout=15, check=False)
    assert result.returncode == -signal.SIGKILL, (
        result.returncode, result.stderr[-1600:]
    )


@pytest.mark.parametrize("mode", ["during_configure", "after_snapshot"])
def test_real_process_death_preserves_verified_snapshot_and_journal(tmp_path, mode):
    cfg, control, bundle, originals = _prepare(tmp_path, mode)
    _kill_child(control)
    snapshot = Path(cfg["snapshot_root"]) / (cfg["transaction_id"] + ".json")
    assert snapshot.is_file()
    assert snapshot.stat().st_mode & 0o077 == 0
    journal = DurableServiceJournal(Path(cfg["journal_root"]), cfg["transaction_id"])
    records = journal.records()
    assert records
    assert journal.recovery_status()["can_auto_replay"] is False
    result = plan_interrupted_recovery(
        snapshot_root=Path(cfg["snapshot_root"]),
        journal_root=Path(cfg["journal_root"]),
        transaction_id=cfg["transaction_id"],
        reviewed_bundle=bundle, service_units=NAMES,
    )
    assert result["state"] == "review_required"
    assert result["can_execute"] is False
    assert result["automatic_replay_allowed"] is False
    assert result["requires_operator_review"] is True
    assert result["prior_unit_states"] == {
        NAMES["web"]: True, NAMES["mailbox"]: False,
    }
    if mode == "during_configure":
        assert result["pending_compensations"] == [
            {"operation": "restore", "service": "web", "unit": NAMES["web"]}]
        assert (Path(cfg["sandbox"]) / "units" / NAMES["web"]).read_bytes() != originals[NAMES["web"]]
    else:
        assert result["pending_compensations"] == []
        assert all((Path(cfg["sandbox"]) / "units" / unit).read_bytes() == data
                   for unit, data in originals.items())
    # Opening the plan must never restore, start or stop units.
    assert result["can_execute"] is False


def test_snapshot_journal_survive_separate_restart_without_auto_replay(tmp_path):
    cfg, control, bundle, originals = _prepare(tmp_path, "during_configure")
    _kill_child(control)
    # Read from a *different* Python process with no inherited objects.
    check = (
        "import json, sys; from pathlib import Path; "
        "sys.path.insert(0, sys.argv[1]); "
        "from onboarding_v2_recovery_preflight import plan_interrupted_recovery; "
        "cfg=json.load(open(sys.argv[2])); bundle=json.load(open(cfg['bundle_file'])); "
        "result=plan_interrupted_recovery("
        "snapshot_root=Path(cfg['snapshot_root']),"
        "journal_root=Path(cfg['journal_root']),"
        "transaction_id=cfg['transaction_id'],"
        "reviewed_bundle=bundle,service_units=cfg['service_units']); "
        "print(json.dumps(result))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", check, str(ROOT), str(control)],
        cwd=ROOT, capture_output=True, text=True, timeout=15, check=False)
    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    assert plan["pending_compensations"][0]["unit"] == NAMES["web"]
    assert plan["requires_operator_review"]
    assert plan["can_execute"] is False
    assert (Path(cfg["sandbox"]) / "units" / NAMES["web"]).read_bytes() != originals[NAMES["web"]]


def test_corrupt_journal_after_sigkill_fails_closed(tmp_path):
    cfg, control, bundle, originals = _prepare(tmp_path, "during_configure")
    _kill_child(control)
    journal = DurableServiceJournal(Path(cfg["journal_root"]), cfg["transaction_id"])
    raw = journal.path.read_bytes()
    journal.path.write_bytes(raw[:-1])
    from onboarding import OnboardingError
    with pytest.raises(OnboardingError):
        plan_interrupted_recovery(
            snapshot_root=Path(cfg["snapshot_root"]),
            journal_root=Path(cfg["journal_root"]),
            transaction_id=cfg["transaction_id"],
            reviewed_bundle=bundle, service_units=NAMES,
        )


def test_no_live_services_or_production_paths_touched(tmp_path):
    cfg, control, bundle, originals = _prepare(tmp_path, "during_configure")
    _kill_child(control)
    assert not (tmp_path / "Caddyfile").exists()
    assert not (tmp_path / "registry.json").exists()
    assert not (tmp_path / "systemctl").exists()
    assert set(os.listdir(cfg["sandbox"])) == {"units", ".uda-sandbox.lock"}
