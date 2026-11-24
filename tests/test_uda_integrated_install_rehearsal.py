"""Full source payload in disposable installation transaction tests."""
import shutil

import pytest

from tools.uda_runtime_integrity import ROOT, payload_paths
from tools.uda_integrated_install_rehearsal import rehearse


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


@pytest.mark.parametrize("scenario,phase", [
    ("success", "complete"),
    ("interrupted", "rolled_back"),
    ("recovery-interrupted", "rolled_back"),
])
def test_full_payload_transaction(stage, scenario, phase):
    result = rehearse(stage, scenario)
    assert result["status"] == "PASS"
    assert result["phase"] == phase
    assert result["payload_count"] == len(payload_paths(ROOT))
    assert result["all_payload_identities_verified"]
    assert result["unmanaged_state_preserved"]
    assert not result["production_files_modified"]
    assert not result["systemctl_invoked"]
    assert not result["production_upgrade_authorized"]


def test_tampered_stage_refused(stage):
    (stage / "runtime/dashboard.py").write_text("tampered")
    with pytest.raises(ValueError, match="differs from source"):
        rehearse(stage)


def test_unknown_scenario_refused(stage):
    with pytest.raises(ValueError, match="Unknown scenario"):
        rehearse(stage, "production")
