import pytest
from test_uda_production_payload_transaction import fixture, assert_old, begin
from test_uda_integrated_release_controller import setup
from tools import uda_production_payload_transaction as t
from tools import uda_integrated_release_controller as c
from tools import uda_release_transaction_journal as j
from tools import uda_production_integrity_gates as g
from tools.uda_production_release_plan import digest


def test_original_receipt_persisted(tmp_path, monkeypatch):
    runtime, stage, journal, plan, adapter, gates = setup(tmp_path, monkeypatch)
    expected = g.environment(runtime / "venv")
    with j.locked(journal) as session:
        assert c.execute(session, stage, runtime, adapter, gates, plan) == "accepted"
        assert session.load()["original_environment"] == expected
    assert g.verify_environment(runtime / "venv-v1-retained", expected)


def test_retained_drift_refused_before_unlink(tmp_path, monkeypatch):
    runtime, stage, journal, plan = fixture(tmp_path, monkeypatch)
    with j.locked(journal) as s:
        begin(s, plan)
        record = s.load()
        record["original_environment"] = g.environment(runtime / "venv")
        s.save(record)
        t.apply(s, stage, runtime)
        t.switch(s, runtime)
        s.advance("recovering")
        (runtime / "venv-v1-retained/marker").write_bytes(b"changed")
        with pytest.raises(ValueError, match="Original environment drift"):
            t.restore_environment(s, runtime)
        assert (runtime / "venv").is_symlink()


def test_new_directories_removed(tmp_path, monkeypatch):
    runtime, stage, journal, plan = fixture(tmp_path, monkeypatch)
    # Add a nested payload by moving a synthetic manifest entry.
    body = plan["contract"]
    old = "runtime/new0.py"
    new = "runtime/fresh/nested/new0.py"
    item = body["mutations"].pop(old)
    body["mutations"][new] = item
    manifest = t.inventory(stage)["files"]
    manifest[new] = manifest.pop(old)
    target = stage / new
    target.parent.mkdir(parents=True, mode=0o700)
    (stage / old).rename(target)
    plan["sha256"] = digest(body)
    with j.locked(journal) as s:
        begin(s, plan)
        t.apply(s, stage, runtime)
        assert (runtime / "fresh/nested/new0.py").exists()
        s.advance("recovering")
        t.restore_files(s, stage, runtime)
        assert not (runtime / "fresh").exists()
        t.restore_files(s, stage, runtime)
        assert_old(runtime, plan)
