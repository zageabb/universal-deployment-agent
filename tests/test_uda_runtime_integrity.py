"""Offline runtime inventory and rollback tests; no production paths."""
from pathlib import Path
import shutil

import pytest

from tools.uda_runtime_integrity import ROOT, inventory, payload_paths, rehearse


@pytest.fixture
def stage(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir(mode=0o700)
    for name, source in payload_paths(ROOT).items():
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        dest.chmod(0o644)
    return root


def test_inventory_matches_source(stage):
    result = inventory(stage)
    assert result["payload_count"] >= 40
    assert result["source_bytes_verified"]
    assert not result["production_upgrade_authorized"]
    assert "runtime/dashboard.py" in result["files"]
    assert "bin/uda-trigger-ci" in result["files"]
    assert not any("venv/" in n or n.startswith("config/") for n in result["files"])


def test_tampered_payload_refused(stage):
    (stage / "runtime/dashboard.py").write_text("tampered")
    with pytest.raises(ValueError, match="differs from source"):
        inventory(stage)


def test_missing_payload_refused(stage):
    (stage / "runtime/dashboard.py").unlink()
    with pytest.raises(ValueError, match="Missing"):
        inventory(stage)


def test_symlink_payload_refused(stage):
    dest = stage / "runtime/dashboard.py"
    dest.unlink()
    dest.symlink_to(ROOT / "dashboard.py")
    with pytest.raises(ValueError, match="Symlink"):
        inventory(stage)


def test_unsafe_mode_refused(stage):
    (stage / "runtime/dashboard.py").chmod(0o666)
    with pytest.raises(ValueError, match="mode"):
        inventory(stage)


def test_nonprivate_stage_refused(stage):
    stage.chmod(0o755)
    with pytest.raises(ValueError, match="owner-private"):
        inventory(stage)


def test_synthetic_failure_rolls_back(stage):
    result = rehearse(stage)
    assert result["status"] == "PASS"
    assert result["previous_bytes_and_modes_restored"]
    assert result["new_files_removed"]
    assert result["unmanaged_state_preserved"]
    assert not result["production_files_modified"]
    assert not result["systemctl_invoked"]
