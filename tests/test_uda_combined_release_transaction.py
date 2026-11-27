import shutil
import pytest
from tools import uda_combined_release_transaction as combined
from tools.uda_runtime_integrity import ROOT, payload_paths


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


@pytest.mark.parametrize("scenario", combined.SCENARIOS)
def test_combined_release(stage, scenario):
    result = combined.rehearse(stage, scenario)
    assert result["status"] == "PASS"
    assert result["phase"] == ("fixture_accepted" if scenario == "success" else "rolled_back")
    assert result["add_count"] == 35
    assert result["replace_count"] == 6
    assert result["preserved_count"] == 21
    assert result["sigkill_injected"] == (scenario not in {"success", "failed_health"})
    assert result["synthetic_environment_markers"]
    assert not result["production_files_modified"]
    assert not result["production_upgrade_authorized"]


def test_tampered_stage(stage):
    (stage / "runtime/dashboard.py").write_text("tampered")
    with pytest.raises(ValueError, match="differs"):
        combined.rehearse(stage, "success")


def test_unknown_scenario(stage):
    with pytest.raises(ValueError, match="Unknown scenario"):
        combined.rehearse(stage, "production")
