import fcntl
import pytest
from tools import uda_v1_writer_protection as w


@pytest.fixture
def lab(tmp_path, monkeypatch):
    paths = tuple(tmp_path / n for n in ("deploy.lock", "proxy-migration.lock"))
    for p in paths:
        p.write_text("legacy evidence")
        p.chmod(0o600)
    monkeypatch.setattr(w, "legacy_paths", lambda home: paths)
    monkeypatch.setattr(w, "scope", lambda home: {"state": tmp_path})
    monkeypatch.setattr(w, "process_indicators", lambda roots: {"findings": []})
    return tmp_path, paths


def test_both_locks_held_and_released(lab):
    home, paths = lab
    with w.hold(home, lambda: True, lambda r: not r["findings"]) as guard:
        assert guard()
        for path in paths:
            with path.open("r+") as contender:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert path.read_text() == "legacy evidence"
    with pytest.raises(ValueError, match="no longer held"):
        guard()
    for path in paths:
        with path.open("r+") as contender:
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_contention_releases_first_lock(lab):
    home, paths = lab
    with paths[1].open("r+") as contender:
        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="worker lock busy"):
            with w.hold(home, lambda: True, lambda _: True):
                pytest.fail("entered")
    with paths[0].open("r+") as contender:
        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_missing_lock_not_created(lab):
    home, paths = lab
    paths[1].unlink()
    with pytest.raises(FileNotFoundError):
        with w.hold(home, lambda: True, lambda _: True):
            pytest.fail("entered")
    assert not paths[1].exists()


def test_freeze_lost(lab):
    home, _ = lab
    frozen = [True]
    with w.hold(home, lambda: frozen[0], lambda _: True) as guard:
        frozen[0] = False
        with pytest.raises(ValueError, match="freeze lost"):
            guard()


def test_unreviewed_process(lab, monkeypatch):
    home, _ = lab
    monkeypatch.setattr(w, "process_indicators", lambda _: {"findings": [{"pid": 123, "indicator": "uninspectable"}]})
    with pytest.raises(ValueError, match="Unresolved"):
        with w.hold(home, lambda: True, lambda r: not r["findings"]):
            pytest.fail("entered")


def test_replaced_lock_refused(lab):
    home, paths = lab
    with w.hold(home, lambda: True, lambda _: True) as guard:
        paths[0].rename(home / "retained")
        paths[0].touch(mode=0o600)
        with pytest.raises(ValueError, match="Unsafe or replaced"):
            guard()


def test_symlink_refused(lab):
    home, paths = lab
    paths[1].unlink()
    paths[1].symlink_to(paths[0])
    with pytest.raises(OSError):
        with w.hold(home, lambda: True, lambda _: True):
            pytest.fail("entered")
