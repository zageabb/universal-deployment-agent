from pathlib import Path
import pytest
from tools import uda_permanent_candidate_venv as c


def test_vacant(tmp_path):
    c.vacant(tmp_path / "missing")
    with pytest.raises(ValueError, match="already exists"):
        c.vacant(tmp_path)


def test_dangling_link_refused(tmp_path):
    path = tmp_path / "candidate"
    path.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError, match="already exists"):
        c.vacant(path)


def test_directory_identity(tmp_path):
    assert c.identity(tmp_path) == c.identity(tmp_path)
    path = tmp_path / "link"
    path.symlink_to(tmp_path)
    with pytest.raises(ValueError, match="Unsafe"):
        c.identity(path)


def test_default_rehearsal(monkeypatch, tmp_path):
    def prepare(stage, destination, lab):
        assert destination.parent == lab
        assert destination.name == "venv-v2"
        destination.mkdir()
        return {"candidate": str(destination)}
    monkeypatch.setattr(c, "prepare", prepare)
    monkeypatch.setattr(c.admission, "inspect", lambda _: pytest.fail("Production admission called"))
    result = c.execute(tmp_path)
    assert result["status"] == "REHEARSAL_PASS"
    assert not result["production_files_modified"]
    assert not result["live_venv_switched"]
    assert not Path(result["candidate"]).exists()


def test_explicit_creation_requires_admission(monkeypatch, tmp_path):
    monkeypatch.setattr(c.os, "getuid", lambda: 1000)
    def refuse(stage):
        raise ValueError("Baseline refused")
    monkeypatch.setattr(c.admission, "inspect", refuse)
    monkeypatch.setattr(c, "prepare", lambda *args: pytest.fail("Candidate created"))
    with pytest.raises(ValueError, match="Baseline refused"):
        c.execute(tmp_path, True)


def test_root_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(c.os, "getuid", lambda: 0)
    with pytest.raises(ValueError, match="root"):
        c.execute(tmp_path, True)
