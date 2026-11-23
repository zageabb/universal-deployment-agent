"""Synthetic isolated systemd restore rehearsal; no live units are touched."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from tools.v2_snapshot_rehearsal import ARCHIVE_NAME, SnapshotError
from tools.v2_systemd_restore_rehearsal import ENABLED, OVERRIDES, rehearse_units


@pytest.fixture
def recovery_lab(tmp_path, monkeypatch):
    mount = tmp_path / "drive"
    mount.mkdir()
    root = mount / "uda-release"
    root.mkdir(mode=0o700)
    for sub in ("snapshots", "restore-rehearsals", "evidence"):
        (root / sub).mkdir(mode=0o700)
    original = Path.is_mount
    monkeypatch.setattr(Path, "is_mount",
                        lambda self: self == mount or original(self))
    return root, mount


def fixture_snapshot(lab, *, replace=None, missing=None):
    root, mount = lab
    target = root / "snapshots" / "uda-fixture"
    target.mkdir(mode=0o700)
    replace = replace or {}
    archive = target / ARCHIVE_NAME
    items = {}
    for link, unit in ENABLED.items():
        items["systemd-user/" + link] = ("link", "/home/test/.config/systemd/user/" + unit)
    for unit in (*ENABLED.values(), *OVERRIDES):
        items["systemd-user/" + unit] = ("file", "[Unit]\nDescription=Synthetic\n")
    items.update(replace)
    if missing:
        items.pop(missing)
    with tarfile.open(archive, "w:gz") as tf:
        for name, (kind, value) in items.items():
            info = tarfile.TarInfo(name)
            if kind == "link":
                info.type = tarfile.SYMTYPE
                info.linkname = value
                tf.addfile(info)
            else:
                data = value.encode()
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
    (target / "manifest.json").write_text(json.dumps({
        "archive": ARCHIVE_NAME,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }))
    return target


def test_five_units_and_overrides_are_reconstructed_offline(recovery_lab):
    snapshot = fixture_snapshot(recovery_lab)
    root, mount = recovery_lab
    result = rehearse_units(snapshot, root=root, mountpoint=mount)
    assert result["status"] == "PASS"
    assert result["uda_links_reconstructed"] == 5
    assert result["environment_overrides_present"] == 2
    assert result["unrelated_links_reconstructed"] == 0
    assert result["systemctl_invoked"] is False
    assert result["full_systemd_restore_rehearsed"] is False
    assert not list((root / "restore-rehearsals").iterdir())


@pytest.mark.parametrize("link_target", [
    "/etc/systemd/system/deployment-agent.timer",
    "/tmp/deployment-agent.timer",
    "../../deployment-agent.timer",
    "/home/test/.config/systemd/user/../deployment-agent.timer",
])
def test_unsafe_archived_target_refused(recovery_lab, link_target):
    link = "systemd-user/timers.target.wants/deployment-agent.timer"
    snapshot = fixture_snapshot(recovery_lab, replace={
        link: ("link", link_target),
    })
    root, mount = recovery_lab
    with pytest.raises(SnapshotError, match="Unsafe UDA"):
        rehearse_units(snapshot, root=root, mountpoint=mount)


def test_required_unit_missing_fails_closed(recovery_lab):
    snapshot = fixture_snapshot(recovery_lab,
                                missing="systemd-user/deployment-agent.timer")
    root, mount = recovery_lab
    with pytest.raises(SnapshotError, match="missing"):
        rehearse_units(snapshot, root=root, mountpoint=mount)


def test_tampered_snapshot_refused(recovery_lab):
    snapshot = fixture_snapshot(recovery_lab)
    (snapshot / ARCHIVE_NAME).open("ab").write(b"tamper")
    root, mount = recovery_lab
    with pytest.raises(SnapshotError, match="SHA-256"):
        rehearse_units(snapshot, root=root, mountpoint=mount)


def test_no_backup_mount_refuses(recovery_lab, monkeypatch):
    snapshot = fixture_snapshot(recovery_lab)
    root, mount = recovery_lab
    monkeypatch.setattr(Path, "is_mount", lambda self: False)
    with pytest.raises(SnapshotError, match="not mounted"):
        rehearse_units(snapshot, root=root, mountpoint=mount)

