import sqlite3
import pytest
from test_uda_production_payload_transaction import fixture, begin
from test_uda_production_service_isolation import Adapter, baseline
from tools.uda_controlled_activation import TIMERS, WEB
from tools import uda_quiesced_backup as b
from tools import uda_release_transaction_journal as j


@pytest.fixture
def lab(tmp_path, monkeypatch):
    runtime, stage, journal, plan = fixture(tmp_path, monkeypatch)
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    with sqlite3.connect(source / "identity.db") as db:
        db.execute("CREATE TABLE example (id INTEGER)")
    output = tmp_path / "output"
    output.mkdir(mode=0o700)
    adapter = Adapter()
    for u in TIMERS + WEB:
        adapter.change("stop", u)
    # The actual approval validator is tested separately.
    monkeypatch.setattr(b, "approval", lambda *args: True)
    return journal, plan, {"runtime": source}, output / "backup.tar", adapter


def test_backup_creation(lab):
    journal, plan, roots, dest, adapter = lab
    with j.locked(journal) as session:
        begin(session, plan)
        report = b.create(session, adapter, baseline(), roots, dest, {}, lambda: True)
        assert report["status"] == "SELECTED_ROOT_BACKUP_PASS"
        assert report["sqlite_checked"] == ["runtime/identity.db"]
        assert session.load()["backup_evidence"]["archive_sha256"] == report["archive_sha256"]
        assert dest.stat().st_mode & 0o777 == 0o600


def test_writer_refusal(lab):
    journal, plan, roots, dest, adapter = lab
    with j.locked(journal) as session:
        begin(session, plan)
        with pytest.raises(ValueError, match="Writer exclusion"):
            b.create(session, adapter, baseline(), roots, dest, {}, lambda: False)
        assert not dest.exists()


def test_active_service_refusal(lab):
    journal, plan, roots, dest, adapter = lab
    with j.locked(journal) as session:
        begin(session, plan)
        with pytest.raises(ValueError, match="not isolated"):
            b.create(session, Adapter(), baseline(), roots, dest, {}, lambda: True)
        assert not dest.exists()


def test_existing_archive_refusal(lab):
    journal, plan, roots, dest, adapter = lab
    dest.write_bytes(b"preserve")
    with j.locked(journal) as session:
        begin(session, plan)
        with pytest.raises(FileExistsError):
            b.create(session, adapter, baseline(), roots, dest, {}, lambda: True)
    assert dest.read_bytes() == b"preserve"


def test_destination_inside_source(lab):
    journal, plan, roots, dest, adapter = lab
    with j.locked(journal) as session:
        begin(session, plan)
        with pytest.raises(ValueError, match="inside source"):
            b.create(session, adapter, baseline(), roots, roots["runtime"] / "backup.tar", {}, lambda: True)


def test_guard_lost_after_archive(lab):
    journal, plan, roots, dest, adapter = lab
    checks = iter([True, True, False])
    with j.locked(journal) as session:
        begin(session, plan)
        with pytest.raises(ValueError, match="Writer exclusion"):
            b.create(session, adapter, baseline(), roots, dest, {}, lambda: next(checks))
        assert "backup_evidence" not in session.load()
