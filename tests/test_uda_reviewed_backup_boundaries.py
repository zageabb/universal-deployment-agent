from pathlib import Path
import pytest
from tools import uda_reviewed_backup_boundaries as b


@pytest.fixture
def lab(tmp_path, monkeypatch):
    home = tmp_path
    roots = {"runtime": home / ".local/share/deployment-agent",
             "config": home / ".config/deployment-agent",
             "state": home / ".local/state/deployment-agent"}
    units = home / ".config/systemd/user"
    binary = home / ".local/bin"
    for p in (*roots.values(), units, binary):
        p.mkdir(parents=True, mode=0o700)
    for name in (*b.UNIT_FILES, *b.OVERRIDES):
        p = units / name
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        p.write_text("fixture")
        p.chmod(0o600)
    for name, unit in b.ENABLED.items():
        p = units / name
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        p.symlink_to("../" + unit)
    (binary / "uda-trigger-ci").write_text("fixture")
    (binary / "uda-trigger-ci").chmod(0o600)
    (roots["runtime"] / "dashboard.py").write_text("fixture")
    monkeypatch.setattr(b, "scope", lambda _: roots)
    monkeypatch.setattr(b, "payload_paths", lambda _: {"runtime/dashboard.py": Path("dashboard.py")})
    return home, roots, units


def test_exact_assets(lab):
    home, roots, units = lab
    report = b.review(home)
    assert report["status"] == "DISCOVERY_PASS"
    assert len(report["rollback_assets"]) == 11
    assert len(report["enablement_links"]) == 5
    assert report["backup_scope_complete"] is False


def test_unknown_entries(lab):
    home, roots, units = lab
    (roots["runtime"] / "unclassified").mkdir()
    assert b.review(home)["runtime_unclassified"] == ["unclassified"]


def test_application_proposal(lab):
    home, roots, units = lab
    (roots["runtime"] / "sci-next-releases").mkdir(mode=0o700)
    report = b.review(home, reviewed_application_dirs=["sci-next-releases"])
    assert report["status"] == "REVIEW"
    assert report["proposed_application_exclusions"] == ["sci-next-releases"]
    assert report["writer_exclusion_verified"] is False


def test_unreviewed_exclusion(lab):
    home, roots, units = lab
    with pytest.raises(ValueError, match="Unreviewed application"):
        b.review(home, reviewed_application_dirs=["other-releases"])


def test_wrong_enablement_link(lab):
    home, roots, units = lab
    name = next(iter(b.ENABLED))
    p = units / name
    p.unlink()
    p.symlink_to("../" + b.UNIT_FILES[-1])
    with pytest.raises(ValueError, match="Unexpected enablement"):
        b.review(home)


def test_missing_override(lab):
    home, roots, units = lab
    (units / b.OVERRIDES[0]).unlink()
    with pytest.raises(ValueError, match="Missing rollback asset"):
        b.review(home)
