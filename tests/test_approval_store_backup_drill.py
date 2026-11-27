"""Disposable backup/restore safety tests; never reference production files."""
from __future__ import annotations

import sqlite3

from approval_centre import create_request, decide, overview
from tools.approval_store_backup_drill import copy_verified, main

SHA = "a" * 40


def fixture(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir(mode=0o700)
    source = storage / "source.sqlite3"
    ident = create_request(source, application="example", action="deploy",
                           scope="disposable storage rehearsal", source_sha=SHA,
                           reason="Test source for private backup restore")
    decide(source, ident, decision="approved",
           reason="Isolated review decision for backup")
    output = tmp_path / "output"
    output.mkdir(mode=0o700)
    return source, output


def test_backup_and_disposable_restore_preserves_audit(tmp_path, capsys):
    source, output = fixture(tmp_path)
    before = source.read_bytes()
    backup, restore = output / "backup.db", output / "restored.db"
    assert main(["--source", str(source), "--backup", str(backup),
                 "--restore-test", str(restore)]) == 0
    result = capsys.readouterr().out
    assert '"result": "PASS"' in result
    assert "Test source for private" not in result
    assert source.read_bytes() == before
    assert backup.stat().st_mode & 0o077 == 0
    assert restore.stat().st_mode & 0o077 == 0
    assert [row["event"] for row in overview(restore)[1]] == ["approved", "requested"]
    assert [row["status"] for row in overview(restore)[0]] == ["approved"]


def test_existing_backup_is_never_overwritten(tmp_path):
    source, output = fixture(tmp_path)
    backup = output / "backup.db"
    backup.write_bytes(b"KEEP")
    assert main(["--source", str(source), "--backup", str(backup),
                 "--restore-test", str(output / "restored.db")]) == 1
    assert backup.read_bytes() == b"KEEP"
    assert not (output / "restored.db").exists()


def test_public_destination_directory_rejected(tmp_path):
    source, output = fixture(tmp_path)
    output.chmod(0o755)
    assert main(["--source", str(source), "--backup", str(output / "backup.db"),
                 "--restore-test", str(output / "restored.db")]) == 1
    assert not (output / "backup.db").exists()


def test_symlink_destination_not_followed(tmp_path):
    source, output = fixture(tmp_path)
    link = output / "backup.db"
    link.symlink_to(source)
    assert main(["--source", str(source), "--backup", str(link),
                 "--restore-test", str(output / "restored.db")]) == 1
    assert not (output / "restored.db").exists()


def test_nonexistent_source_not_created(tmp_path):
    output = tmp_path / "output"
    output.mkdir(mode=0o700)
    missing = tmp_path / "missing.db"
    assert main(["--source", str(missing), "--backup", str(output / "backup.db"),
                 "--restore-test", str(output / "restored.db")]) == 1
    assert not missing.exists()
    assert not (output / "backup.db").exists()


def test_backup_source_can_have_live_wal_writer(tmp_path):
    source, output = fixture(tmp_path)
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("INSERT INTO audit(request_id,event,actor,at,reason) "
                   "VALUES(?,?,?,?,?)",
                   ("synthetic", "requested", "reviewer", "2026-01-01", "fixture"))
        db.commit()
        report = copy_verified(source, output / "wal-backup.db")
        assert report["result"] == "PASS"
    assert any(row["request_id"] == "synthetic"
               for row in overview(output / "wal-backup.db")[1])
