"""Read-only production inventory tests on disposable roots."""
import shutil
import pytest
from tools.uda_runtime_integrity import ROOT, payload_paths
from tools.uda_controlled_activation import UNITS
from tools import uda_production_replacement_plan as p


@pytest.fixture
def lab(tmp_path):
    home = tmp_path / "home"
    stage = tmp_path / "stage"
    stage.mkdir(mode=0o700)
    roots = {"runtime": home / ".local/share/deployment-agent",
             "units": home / ".config/systemd/user", "bin": home / ".local/bin"}
    for root in roots.values():
        root.mkdir(parents=True)
        root.chmod(0o755)
    for name, source in payload_paths(ROOT).items():
        dest = stage / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        dest.chmod(0o644)
    for unit in UNITS:
        (roots["units"] / unit).write_text("existing local definition")
        (roots["units"] / unit).chmod(0o644)
    return stage, home, roots


def test_add_replace_unchanged_and_preserve(lab):
    stage, home, roots = lab
    shutil.copyfile(stage / "runtime/dashboard.py", roots["runtime"] / "dashboard.py")
    (roots["runtime"] / "dashboard.py").chmod(0o644)
    (roots["runtime"] / "home.py").write_text("old")
    (roots["runtime"] / "home.py").chmod(0o644)
    result = p.collect(stage, home)
    assert result["status"] == "PASS", result["issues"]
    assert result["entries"]["runtime/dashboard.py"]["action"] == "unchanged"
    assert result["entries"]["runtime/home.py"]["action"] == "replace"
    assert result["entries"]["runtime/deploy_agent.py"]["action"] == "add"
    assert result["entries"]["units/deployment-agent.service"]["action"] == "preserve_review"
    assert result["entries"]["bin/uda-trigger-ci"]["action"] == "preserve_review"
    assert not result["production_upgrade_authorized"]
    assert (roots["runtime"] / "home.py").read_text() == "old"


def test_missing_proxy_unit_requires_review(lab):
    stage, home, roots = lab
    (roots["units"] / "uda-proxy-refresh.service").unlink()
    result = p.collect(stage, home)
    assert result["status"] == "REVIEW"
    assert result["units"]["uda-proxy-refresh.service"]["status"] == "missing"


def test_symlink_refused(lab):
    stage, home, roots = lab
    (roots["runtime"] / "home.py").symlink_to(stage / "runtime/home.py")
    result = p.collect(stage, home)
    assert result["entries"]["runtime/home.py"]["action"] == "blocked"


def test_group_writable_root_requires_review(lab):
    stage, home, roots = lab
    roots["runtime"].chmod(0o775)
    assert p.collect(stage, home)["status"] == "REVIEW"


def test_hardlink_refused(lab):
    stage, home, roots = lab
    import os
    os.link(stage / "runtime/home.py", roots["runtime"] / "home.py")
    assert p.collect(stage, home)["entries"]["runtime/home.py"]["action"] == "blocked"


def test_stage_tamper_refused(lab):
    stage, home, roots = lab
    (stage / "runtime/home.py").write_text("tampered")
    with pytest.raises(ValueError, match="differs"):
        p.collect(stage, home)


def test_group_writable_file_requires_review(lab):
    stage, home, roots = lab
    path = roots["runtime"] / "home.py"
    path.write_text("old")
    path.chmod(0o664)
    result = p.collect(stage, home)
    assert result["status"] == "REVIEW"
    assert result["entries"]["runtime/home.py"]["installed"]["status"] == "unsafe_metadata"
