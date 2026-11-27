from pathlib import Path
import tarfile
import pytest
from tools import uda_selected_backup_assets as s
from tools.uda_backup_inventory import capture, verify_snapshot
from tools.v2_systemd_restore_rehearsal import UNIT_FILES, OVERRIDES, ENABLED


@pytest.fixture
def lab(tmp_path, monkeypatch):
    home = tmp_path
    roots = {"runtime": home / ".local/share/deployment-agent",
             "config": home / ".config/deployment-agent",
             "state": home / ".local/state/deployment-agent"}
    units = home / ".config/systemd/user"
    binary = home / ".local/bin"
    for path in (*roots.values(), units, binary):
        path.mkdir(parents=True, mode=0o700)
    runtime = roots["runtime"]
    release = runtime / "sci-next-releases" / "fixture-release"
    release.mkdir(parents=True)
    (release / "app.py").write_text("application")
    (runtime / "sci-next-current").symlink_to(release)
    (runtime / "dashboard.py").write_text("fixture")
    (runtime / "publishers").mkdir()
    (runtime / "publishers" / "asset").write_text("preserve")
    for name in (*UNIT_FILES, *OVERRIDES):
        p = units / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("unit")
    for name, unit in ENABLED.items():
        p = units / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.symlink_to("../" + unit)
    (units / "unrelated.service").write_text("unrelated")
    (binary / "uda-trigger-ci").write_text("wrapper")
    (binary / "unrelated").write_text("unrelated")
    monkeypatch.setattr(s, "scope", lambda _: dict(roots))
    monkeypatch.setattr(s, "review", lambda *a, **k: {"runtime_unclassified": ["publishers", "sci-next-current"]})
    return home, runtime


def test_exact_selection(lab):
    home, runtime = lab
    roots, selected, excluded = s.selection(home)
    entries = capture(roots, selected=selected, excluded=excluded)
    assert "runtime/sci-next-current" in entries
    assert "runtime/sci-next-releases" not in entries
    assert "runtime/publishers/asset" in entries
    assert "systemd-user/unrelated.service" not in entries
    assert "bin/unrelated" not in entries
    assert s.inspect(home)["rollback_assets_present"] == 16


def test_archive_matches_selection(lab):
    home, runtime = lab
    roots, selected, excluded = s.selection(home)
    entries = capture(roots, selected=selected, excluded=excluded)
    archive = home / "backup.tar"
    with tarfile.open(archive, "w", dereference=False) as tar:
        for name, root in sorted(roots.items()):
            tar.add(root, arcname=name, filter=lambda member: member if member.name in entries else None)
    assert verify_snapshot(archive, roots, entries, selected=selected, excluded=excluded)["status"] == "INVENTORY_PASS"
    assert (runtime / "sci-next-releases/fixture-release/app.py").read_text() == "application"


def test_unknown_runtime_refused(lab, monkeypatch):
    home, _ = lab
    monkeypatch.setattr(s, "review", lambda *a, **k: {"runtime_unclassified": ["unreviewed"]})
    with pytest.raises(ValueError, match="Unclassified"):
        s.selection(home)


def test_pointer_escape_refused(lab):
    home, runtime = lab
    pointer = runtime / "sci-next-current"
    pointer.unlink()
    pointer.symlink_to(home)
    with pytest.raises(ValueError, match="Unexpected SCI Next"):
        s.selection(home)
