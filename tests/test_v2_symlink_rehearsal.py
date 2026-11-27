"""Offline symlink audit tests; archives are synthetic and never extracted."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path
import tarfile

import pytest

from tools.v2_symlink_rehearsal import audit
from tools.v2_snapshot_rehearsal import ARCHIVE_NAME, SnapshotError


def archive_with_links(tmp_path, links):
    folder = tmp_path / "snapshot"
    folder.mkdir()
    archive = folder / ARCHIVE_NAME
    with tarfile.open(archive, "w:gz") as tf:
        for name in ("systemd-user", "systemd-user/timers.target.wants"):
            item = tarfile.TarInfo(name)
            item.type = tarfile.DIRTYPE
            tf.addfile(item)
        data = b"[Timer]\n"
        item = tarfile.TarInfo("systemd-user/deployment-agent.timer")
        item.size = len(data)
        tf.addfile(item, io.BytesIO(data))
        for name, target in links:
            item = tarfile.TarInfo(name)
            item.type = tarfile.SYMTYPE
            item.linkname = target
            tf.addfile(item)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (folder / "manifest.json").write_text(
        json.dumps({"sha256": checksum, "archive": ARCHIVE_NAME}))
    return folder


def test_internal_systemd_enablement_symlink_is_resolved_without_creating_it(tmp_path):
    snapshot = archive_with_links(tmp_path, [
        ("systemd-user/timers.target.wants/deployment-agent.timer",
         "../deployment-agent.timer"),
    ])
    result = audit(snapshot)
    assert result["status"] == "PASS"
    assert result["classification"]["internal_regular_target"] == 1
    assert result["links_recreated"] is False
    assert result["systemd_enablement_restored"] is False
    assert result["production_upgrade_authorized"] is False


def test_external_or_absolute_symlinks_are_reported_for_review(tmp_path):
    snapshot = archive_with_links(tmp_path, [
        ("systemd-user/timers.target.wants/deployment-agent.timer", "/etc/systemd/system/other.timer"),
        ("systemd-user/timers.target.wants/proxy.timer", "../../../outside.timer"),
    ])
    result = audit(snapshot)
    assert result["link_count"] == 2
    assert result["classification"]["absolute_target"] == 1
    assert result["classification"]["outside_archive"] == 1
    assert result["links_recreated"] is False


def test_missing_internal_target_is_reported(tmp_path):
    snapshot = archive_with_links(tmp_path, [
        ("systemd-user/timers.target.wants/missing.timer", "../missing.timer"),
    ])
    result = audit(snapshot)
    assert result["classification"]["missing_internal_target"] == 1


def test_checksum_tampering_fails_closed(tmp_path):
    snapshot = archive_with_links(tmp_path, [])
    (snapshot / ARCHIVE_NAME).open("ab").write(b"tamper")
    with pytest.raises(SnapshotError, match="checksum"):
        audit(snapshot)


def test_path_traversal_archive_is_rejected(tmp_path):
    snapshot = archive_with_links(tmp_path, [])
    archive = snapshot / ARCHIVE_NAME
    with tarfile.open(archive, "w:gz") as tf:
        item = tarfile.TarInfo("../escape")
        item.size = 0
        tf.addfile(item, io.BytesIO(b""))
    (snapshot / "manifest.json").write_text(json.dumps({
        "archive": ARCHIVE_NAME,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }))
    with pytest.raises(SnapshotError, match="Noncanonical"):
        audit(snapshot)


def test_duplicate_archive_member_is_rejected(tmp_path):
    snapshot = archive_with_links(tmp_path, [])
    archive = snapshot / ARCHIVE_NAME
    with tarfile.open(archive, "w:gz") as tf:
        for _ in range(2):
            item = tarfile.TarInfo("systemd-user/deployment-agent.timer")
            item.size = 0
            tf.addfile(item, io.BytesIO(b""))
    (snapshot / "manifest.json").write_text(json.dumps({
        "archive": ARCHIVE_NAME,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }))
    with pytest.raises(SnapshotError, match="Duplicate"):
        audit(snapshot)


def test_direct_script_cli_runs_from_repository_root(tmp_path):
    snapshot = archive_with_links(tmp_path, [
        ("systemd-user/timers.target.wants/deployment-agent.timer",
         "../deployment-agent.timer"),
    ])
    root = Path(__file__).resolve().parents[1]
    run = subprocess.run(
        [sys.executable, "tools/v2_symlink_rehearsal.py",
         "--snapshot-dir", str(snapshot)],
        cwd=root, capture_output=True, text=True, timeout=20, check=False,
    )
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result["archive_checksum_ok"] is True
    assert result["classification"]["internal_regular_target"] == 1
    assert result["production_upgrade_authorized"] is False
