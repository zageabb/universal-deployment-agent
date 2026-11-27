import json
import os
import pytest
from tools import uda_production_backup_scope as s


@pytest.fixture
def home(tmp_path, monkeypatch):
    for key in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(key, raising=False)
    for name in (".local/share/deployment-agent", ".config/deployment-agent", ".local/state/deployment-agent"):
        (tmp_path / name).mkdir(parents=True, mode=0o700)
    (tmp_path / ".config/deployment-agent/config.json").write_text("{}")
    return tmp_path


def test_scope(home):
    assert set(s.scope(home)) == {"runtime", "config", "state"}


def test_external_database(home):
    (home / ".config/deployment-agent/config.json").write_text(json.dumps({"identity_db": "/outside/identity.db"}))
    with pytest.raises(ValueError, match="External configured state"):
        s.scope(home)


def test_nonstandard_xdg(home, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", "/outside")
    with pytest.raises(ValueError, match="Nonstandard XDG"):
        s.scope(home)


def test_process_indicators(home, tmp_path):
    roots = s.scope(home)
    proc = tmp_path / "fake-proc"
    process = proc / str(os.getpid() + 100000)
    (process / "fd").mkdir(parents=True)
    (process / "fd/4").symlink_to(roots["state"] / "identity.db")
    report = s.process_indicators(roots, proc)
    assert report["status"] == "REVIEW"
    assert report["findings"][0]["indicator"] == "4"
    assert report["writer_exclusion_verified"] is False


def test_no_indicators(home, tmp_path):
    proc = tmp_path / "fake-proc"
    proc.mkdir()
    report = s.process_indicators(s.scope(home), proc)
    assert report["status"] == "NO_INDICATORS"
    assert report["writer_exclusion_verified"] is False
