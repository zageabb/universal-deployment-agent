"""Offline tests for inactive release preparation and systemd previews."""
import json
from pathlib import Path

import pytest

from onboarding import OnboardingError
from onboarding_release import prepare_release, systemd_unit_preview


def setup_source(tmp_path):
    sha = "a" * 40
    source_root = tmp_path / "staging"
    release_root = tmp_path / "releases"
    source_root.mkdir()
    release_root.mkdir()
    src = source_root / f"demo-{sha[:12]}"
    src.mkdir()
    (src / ".git").mkdir()
    (src / ".git" / "config").write_text("internal metadata")
    (src / "app.py").write_text("print('hello')\n")
    (src / "settings").mkdir()
    (src / "settings" / "readme.txt").write_text("settings")
    staged = {"application": "demo", "commit_sha": sha,
              "repository": "zageabb/demo", "staged_path": str(src)}
    return staged, source_root, release_root, src


def test_assemble_inactive_release_with_receipt(tmp_path):
    staged, staging, releases, src = setup_source(tmp_path)
    result = prepare_release(staged, staging, releases)
    target = Path(result["release_path"])
    receipt = json.loads((target / ".uda-release.json").read_text())
    assert result["status"] == "prepared_inactive"
    assert result["service_started"] is False
    assert result["registry_modified"] is False
    assert result["file_count"] == 2
    assert (target / "app.py").read_text() == src.joinpath("app.py").read_text()
    assert not (target / ".git").exists()
    assert receipt["commit_sha"] == staged["commit_sha"]
    assert len(receipt["files"]) == 2


def test_prepared_release_cannot_be_overwritten(tmp_path):
    staged, staging, releases, _ = setup_source(tmp_path)
    prepare_release(staged, staging, releases)
    with pytest.raises(OnboardingError, match="already prepared"):
        prepare_release(staged, staging, releases)


def test_staging_path_must_match_expected_identity(tmp_path):
    staged, staging, releases, _ = setup_source(tmp_path)
    staged["staged_path"] = str(staging.parent)
    with pytest.raises(OnboardingError, match="approved child"):
        prepare_release(staged, staging, releases)


def test_reject_symlink_from_repo(tmp_path):
    staged, staging, releases, source = setup_source(tmp_path)
    (source / "escape").symlink_to("/etc/passwd")
    with pytest.raises(OnboardingError, match="Symbolic links"):
        prepare_release(staged, staging, releases)
    assert not list(releases.iterdir())


def test_collision_with_reserved_receipt_name(tmp_path):
    staged, staging, releases, source = setup_source(tmp_path)
    (source / ".uda-release.json").write_text("forgery")
    with pytest.raises(OnboardingError, match="conflicts"):
        prepare_release(staged, staging, releases)
    # No completed release exists.
    assert not any((releases / "demo").glob("a" * 40))


def test_reject_release_inside_source(tmp_path):
    staged, staging, _, source = setup_source(tmp_path)
    nested = source / "releases"
    nested.mkdir()
    with pytest.raises(OnboardingError, match="must be separate"):
        prepare_release(staged, staging, nested)


def test_systemd_unit_preview_does_not_activate(tmp_path):
    staged, staging, releases, _ = setup_source(tmp_path)
    prepared = prepare_release(staged, staging, releases)
    plan = {"application": "demo", "service_unit": "uda-demo.service",
            "port": 5200, "entrypoint_pending_approval": ["python", "app.py"]}
    unit = systemd_unit_preview(plan, Path(prepared["release_path"]),
                                environment_file=tmp_path / "private.env")
    assert "ExecStart=" in unit
    assert 'Environment=PORT=5200' in unit
    assert "NoNewPrivileges=yes" in unit
    assert "PREVIEW ONLY" in unit
    assert not list(tmp_path.glob("*.service"))


def test_systemd_preview_refuses_bad_entrypoint(tmp_path):
    staged, staging, releases, _ = setup_source(tmp_path)
    prepared = prepare_release(staged, staging, releases)
    plan = {"application": "demo", "service_unit": "uda-demo.service",
            "port": 5200, "entrypoint_pending_approval": ["python", "app.py\n[Install]"]}
    with pytest.raises(OnboardingError, match="Invalid service argument"):
        systemd_unit_preview(plan, Path(prepared["release_path"]),
                             environment_file=tmp_path / "private.env")
