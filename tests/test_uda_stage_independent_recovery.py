import shutil
import hashlib
import pytest
from test_uda_production_payload_transaction import fixture, begin, assert_old
from tools import uda_production_payload_transaction as t
from tools import uda_release_transaction_journal as j


@pytest.mark.parametrize("damage", ["deleted", "corrupt", "unreadable"])
def test_rollback_without_stage(tmp_path, monkeypatch, damage):
    runtime, stage, journal, plan = fixture(tmp_path, monkeypatch)
    with j.locked(journal) as s:
        begin(s, plan)
        t.apply(s, stage, runtime)
        t.switch(s, runtime)
    if damage == "deleted":
        shutil.rmtree(stage)
    elif damage == "corrupt":
        (stage / "runtime/dashboard.py").write_bytes(b"corrupt")
    else:
        stage.chmod(0)
    monkeypatch.setattr(t, "inventory", lambda _: pytest.fail("rollback accessed stage"))
    try:
        with j.locked(journal) as s:
            s.advance("recovering")
            t.restore_environment(s, runtime)
            t.restore_files(s, stage, runtime)
            t.restore_files(s, None, runtime)
            assert_old(runtime, plan)
    finally:
        if damage == "unreadable":
            stage.chmod(0o700)


def test_missing_stage_before_apply(tmp_path, monkeypatch):
    runtime, stage, journal, plan = fixture(tmp_path, monkeypatch)
    with j.locked(journal) as s:
        begin(s, plan)
        shutil.rmtree(stage)
        monkeypatch.setattr(t, "inventory", lambda _: pytest.fail("rollback accessed stage"))
        s.advance("recovering")
        t.restore_files(s, None, runtime)
        assert_old(runtime, plan)


@pytest.mark.parametrize("damage", ["manifest", "missing_manifest", "backup"])
def test_damaged_evidence_refused_before_file_restore(tmp_path, monkeypatch, damage):
    runtime, stage, journal, plan = fixture(tmp_path, monkeypatch)
    with j.locked(journal) as s:
        begin(s, plan)
        t.apply(s, stage, runtime)
        s.advance("recovering")
        record = s.load()
        if damage == "manifest":
            record["rollback_manifest"]["runtime/dashboard.py"]["sha256"] = "0" * 64
            s.save(record)
        elif damage == "missing_manifest":
            del record["rollback_manifest"]
            s.save(record)
        else:
            key = hashlib.sha256(b"runtime/dashboard.py").hexdigest()
            (journal / "payload-backup" / key).write_bytes(b"corrupt")
        before = {n: t.file_identity(runtime, n.removeprefix("runtime/"))
                  for n in plan["contract"]["mutations"]}
        with pytest.raises(ValueError, match="manifest|Backup integrity"):
            t.restore_files(s, None, runtime)
        assert before == {n: t.file_identity(runtime, n.removeprefix("runtime/"))
                          for n in plan["contract"]["mutations"]}
