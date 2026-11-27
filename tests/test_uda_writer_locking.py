import fcntl
import pytest
import deploy_agent


def test_contended_deploy_lock_preserves_contents(tmp_path, monkeypatch):
    path = tmp_path / "deploy.lock"
    path.write_text("existing evidence")
    monkeypatch.setattr(deploy_agent, "configure_logging",
                        lambda *a: pytest.fail("Logging before lock acquisition"))
    with path.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(deploy_agent.DeployError, match="Another deployment"):
            deploy_agent.execute({"lock_file": str(path), "applications": []}, True, False)
    assert path.read_text() == "existing evidence"


def test_state_write_inside_deploy_lock(tmp_path, monkeypatch):
    path = tmp_path / "deploy.lock"
    checks = []
    def check(*a, **k):
        with path.open("a") as contender:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        checks.append(True)
    monkeypatch.setattr(deploy_agent, "configure_logging", check)
    monkeypatch.setattr(deploy_agent, "write_state", check)
    assert deploy_agent.execute({"lock_file": str(path), "applications": []}, True, False) == []
    assert checks == [True, True]
    with path.open("a") as contender:
        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
