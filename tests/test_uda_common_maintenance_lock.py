import os
import pytest
import deploy_agent as d


@pytest.fixture
def config(tmp_path):
    return {"lock_file": str(tmp_path / "deploy.lock"), "applications": []}


def test_shared_workers_coexist(config):
    with d.maintenance_lock(config):
        with d.maintenance_lock(config):
            with pytest.raises(d.DeployError, match="maintenance lock busy"):
                with d.maintenance_lock(config, exclusive=True):
                    pytest.fail("exclusive lock acquired")


def test_exclusive_blocks_worker(config, monkeypatch):
    monkeypatch.setattr(d, "_execute_locked", lambda *a: pytest.fail("worker entered"))
    with d.maintenance_lock(config, exclusive=True):
        with pytest.raises(d.DeployError, match="maintenance lock busy"):
            d.execute(config, True, False)
    with d.maintenance_lock(config):
        pass


def test_lock_contents_preserved(config):
    path = d.maintenance_lock_path(config)
    path.write_text("preserve")
    path.chmod(0o600)
    with d.maintenance_lock(config):
        assert path.read_text() == "preserve"


def test_symlink_refused(config, tmp_path):
    target = tmp_path / "target"
    target.write_text("preserve")
    d.maintenance_lock_path(config).symlink_to(target)
    with pytest.raises(OSError):
        with d.maintenance_lock(config):
            pytest.fail("unsafe lock acquired")
    assert target.read_text() == "preserve"


def test_hardlink_refused(config, tmp_path):
    target = tmp_path / "target"
    target.touch(mode=0o600)
    os.link(target, d.maintenance_lock_path(config))
    with pytest.raises(d.DeployError, match="Unsafe maintenance lock"):
        with d.maintenance_lock(config):
            pytest.fail("unsafe lock acquired")


def test_unsafe_mode_refused(config):
    path = d.maintenance_lock_path(config)
    path.touch()
    path.chmod(0o666)
    with pytest.raises(d.DeployError, match="Unsafe maintenance lock"):
        with d.maintenance_lock(config):
            pytest.fail("unsafe lock acquired")
