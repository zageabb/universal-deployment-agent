"""Offline snapshot and recovery tests with synthetic V1 files only."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tarfile

import pytest

from tools.v2_snapshot_rehearsal import (
    ARCHIVE_NAME, SOURCES, SnapshotError, check_destination, snapshot, rehearse,
)


@pytest.fixture
def laboratory(tmp_path, monkeypatch):
    mount = tmp_path / "mounted-drive"
    mount.mkdir()
    root = mount / "uda-release"
    root.mkdir(mode=0o700)
    for name in ("snapshots", "restore-rehearsals", "evidence"):
        (root / name).mkdir(mode=0o700)
    original = Path.is_mount
    monkeypatch.setattr(Path, "is_mount", lambda self: self == mount or original(self))

    sources = {key: tmp_path / ("input-" + key) for key in SOURCES}
    for path in sources.values():
        path.mkdir(mode=0o700)
    for name in ("deploy_agent.py", "dashboard.py"):
        (sources["runtime"] / name).write_text("# synthetic\n")
    (sources["config"] / "config.json").write_text('{"token":"SYNTHETIC-SECRET"}')
    units = sources["systemd-user"]
    (units / "deployment-agent.service").write_text("[Service]\nType=oneshot\n")
    for name in ("home", "dashboard"):
        folder = units / f"deployment-agent-{name}.service.d"
        folder.mkdir()
        (folder / "10-environment.conf").write_text("Environment=FOO=synthetic\n")
    (units / "timers.target.wants").mkdir()
    (units / "timers.target.wants" / "deployment-agent.timer").symlink_to(
        "../deployment-agent.timer"
    )
    (units / "deployment-agent.timer").write_text("[Timer]\n")
    state = sources["state"]
    with sqlite3.connect(state / "identity.db") as db:
        db.execute("create table identities (id integer primary key, name text)")
        db.execute("insert into identities(name) values ('test')")
    (state / "identity.sqlite3").touch()
    (state / "status.json").write_text('{"last_run":null}')
    return root, mount, sources


def test_snapshot_and_disposable_rehearsal(laboratory):
    root, mount, sources = laboratory
    dest = snapshot(root, sources, mountpoint=mount)
    assert (dest / ARCHIVE_NAME).is_file()
    assert (dest / ARCHIVE_NAME).stat().st_mode & 0o777 == 0o600
    manifest = json.loads((dest / "manifest.json").read_text())
    assert manifest["application_wide_consistency_verified"] is False
    result = rehearse(dest, root, mountpoint=mount)
    assert result["archive_sha256_ok"] is True
    assert result["sqlite_quick_check"] == "ok"
    assert result["symlinks_recorded_not_recreated"] >= 1
    assert result["full_systemd_restore_rehearsed"] is False
    assert result["production_upgrade_authorized"] is False
    # A rehearsal never writes into or alters source files.
    with sqlite3.connect(sources["state"] / "identity.db") as db:
        assert db.execute("select count(*) from identities").fetchone()[0] == 1
    assert not list((root / "restore-rehearsals").iterdir())


def test_snapshot_rejects_unmounted_destination(laboratory, monkeypatch):
    root, mount, sources = laboratory
    monkeypatch.setattr(Path, "is_mount", lambda self: False)
    with pytest.raises(SnapshotError, match="not mounted"):
        snapshot(root, sources, mountpoint=mount)


def test_snapshot_rejects_unsafe_workspace_modes(laboratory):
    root, mount, sources = laboratory
    root.chmod(0o755)
    with pytest.raises(SnapshotError, match="0700"):
        snapshot(root, sources, mountpoint=mount)


def test_tampered_archive_is_rejected(laboratory):
    root, mount, sources = laboratory
    dest = snapshot(root, sources, mountpoint=mount)
    with (dest / ARCHIVE_NAME).open("ab") as file:
        file.write(b"tampering")
    with pytest.raises(SnapshotError, match="SHA-256"):
        rehearse(dest, root, mountpoint=mount)


def test_missing_state_source_blocks_snapshot(laboratory):
    root, mount, sources = laboratory
    (sources["state"] / "identity.db").unlink()
    with pytest.raises(SnapshotError, match="Expected identity file"):
        snapshot(root, sources, mountpoint=mount)


def test_archive_contains_original_config_but_not_git_metadata(laboratory):
    root, mount, sources = laboratory
    dest = snapshot(root, sources, mountpoint=mount)
    with tarfile.open(dest / ARCHIVE_NAME, "r:gz") as tf:
        names = set(tf.getnames())
    assert "config/config.json" in names
    assert "state/identity.db" in names
    assert "state/identity.sqlite3" in names
    assert "systemd-user/deployment-agent-dashboard.service.d/10-environment.conf" in names
