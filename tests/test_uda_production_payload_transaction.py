from pathlib import Path
import hashlib
import pytest
from tools import uda_production_payload_transaction as t
from tools import uda_release_transaction_journal as j
from tools.uda_production_release_plan import digest


def fixture(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    stage = tmp_path / "stage"
    journal = tmp_path / "journal"
    for p in (runtime, stage, journal):
        p.mkdir(mode=0o700)
    entries = {}
    manifest = {}
    def write(path, data, mode):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data)
        path.chmod(mode)
    for name in sorted(t.REPLACEMENTS) + [f"runtime/new{i}.py" for i in range(35)]:
        new = b"new:" + name.encode()
        rel = name.removeprefix("runtime/")
        write(stage / name, new, 0o644)
        manifest[name] = {"sha256": hashlib.sha256(new).hexdigest(), "mode": 0o644, "size": len(new)}
        old = None
        if name in t.REPLACEMENTS:
            write(runtime / rel, b"old", 0o640)
            old = {"status": "present", "sha256": hashlib.sha256(b"old").hexdigest(), "mode": 0o640}
        entries[name] = {"old": old, "new": manifest[name], "action": "replace" if old else "add"}
    preserved = {}
    for i in range(24):
        name = f"runtime/keep{i}"
        write(runtime / f"keep{i}", b"preserve", 0o600)
        manifest[name] = {"sha256": hashlib.sha256(b"preserve").hexdigest(), "mode": 0o600, "size": 8}
        preserved[name] = {"status": "present", "sha256": manifest[name]["sha256"], "mode": 0o600}
    live = runtime / "venv"
    new = runtime / "venv-v2"
    live.mkdir(mode=0o700)
    new.mkdir(mode=0o700)
    write(live / "marker", b"old", 0o600)
    write(new / "marker", b"new", 0o600)
    monkeypatch.setattr(t, "inventory", lambda _: {"files": manifest})
    body = {"mutations": entries, "preserved": preserved,
            "venv": {"receipt": {"candidate": str(new), "identity": list(t.identity(new)), "tree_sha256": t.tree(new)}}}
    plan = {"contract": body, "sha256": digest(body), "status": "PLAN_ONLY", "production_upgrade_authorized": False}
    return runtime, stage, journal, plan


def begin(s, p):
    s.begin(p)
    s.advance("isolating")
    s.advance("isolated")


def assert_old(runtime, plan):
    for n,e in plan["contract"]["mutations"].items():
        assert t.file_identity(runtime, n.removeprefix("runtime/")) == t.expected(e["old"])
    for n,e in plan["contract"]["preserved"].items():
        assert t.file_identity(runtime, n.removeprefix("runtime/")) == t.expected(e)
    assert (runtime / "venv/marker").read_bytes() == b"old"
    assert not (runtime / "venv").is_symlink()
    assert not (runtime / "venv-v1-retained").exists()


@pytest.mark.parametrize("boundary", ["before:runtime/dashboard.py", "after:runtime/dashboard.py", "after_rename", "after_link", "complete"])
def test_transaction_recovery(tmp_path, monkeypatch, boundary):
    runtime, stage, journal, plan = fixture(tmp_path, monkeypatch)
    def interrupt(point):
        if point == boundary:
            raise RuntimeError("interrupted")
    with j.locked(journal) as s:
        begin(s, plan)
        if boundary == "complete":
            t.apply(s, stage, runtime)
            t.switch(s, runtime)
            assert s.load()["phase"] == "health"
        else:
            with pytest.raises(RuntimeError, match="interrupted"):
                t.apply(s, stage, runtime, interrupt=interrupt)
                t.switch(s, runtime, interrupt=interrupt)
    with j.locked(journal) as s:
        s.advance("recovering")
        t.restore_environment(s, runtime)
        t.restore_files(s, stage, runtime)
        t.restore_environment(s, runtime)
        t.restore_files(s, stage, runtime)
        assert_old(runtime, plan)


def test_unexpected_runtime_refused(tmp_path, monkeypatch):
    runtime, stage, journal, plan = fixture(tmp_path, monkeypatch)
    with j.locked(journal) as s:
        begin(s, plan)
        t.apply(s, stage, runtime)
        s.advance("recovering")
        (runtime / "dashboard.py").write_bytes(b"unexpected")
        with pytest.raises(ValueError, match="Unexpected runtime bytes"):
            t.restore_files(s, stage, runtime)


def test_candidate_drift_refused(tmp_path, monkeypatch):
    runtime, stage, journal, plan = fixture(tmp_path, monkeypatch)
    with j.locked(journal) as s:
        begin(s, plan)
        t.apply(s, stage, runtime)
        (runtime / "venv-v2/marker").write_bytes(b"unexpected")
        with pytest.raises(ValueError, match="Candidate environment drift"):
            t.switch(s, runtime)
        assert not (runtime / "venv").is_symlink()


def test_recovery_before_apply(tmp_path, monkeypatch):
    runtime, stage, journal, plan = fixture(tmp_path, monkeypatch)
    with j.locked(journal) as s:
        begin(s, plan)
        s.advance("recovering")
        t.restore_files(s, stage, runtime)
        t.restore_environment(s, runtime)
        assert_old(runtime, plan)
