import os
import pytest
from tools import uda_release_transaction_journal as j
from tools.uda_production_release_plan import digest


def plan():
    body = {"venv": {"receipt": {"tree_sha256": "fixture"}}}
    return {"contract": body, "sha256": digest(body), "status": "PLAN_ONLY",
            "production_upgrade_authorized": False}


def test_persistent_transitions(tmp_path):
    tmp_path.chmod(0o700)
    with j.locked(tmp_path) as s:
        s.begin(plan())
        s.advance("isolating")
    with j.locked(tmp_path) as s:
        assert s.load()["sequence"] == 1
        s.advance("isolated")
        s.advance("applying")
        s.advance("recovering")
        assert s.advance("rolled_back")["phase"] == "rolled_back"
        with pytest.raises(ValueError, match="Illegal"):
            s.advance("applying")


def test_lock_exclusion(tmp_path):
    tmp_path.chmod(0o700)
    with j.locked(tmp_path):
        with pytest.raises(BlockingIOError):
            with j.locked(tmp_path):
                pass


def test_existing_transaction_refused(tmp_path):
    tmp_path.chmod(0o700)
    with j.locked(tmp_path) as s:
        s.begin(plan())
        with pytest.raises(ValueError, match="Existing"):
            s.begin(plan())


def test_missing_receipt(tmp_path):
    tmp_path.chmod(0o700)
    p = plan()
    p["contract"]["venv"] = {}
    p["sha256"] = digest(p["contract"])
    with j.locked(tmp_path) as s:
        with pytest.raises(ValueError, match="receipt"):
            s.begin(p)


def test_digest_corruption(tmp_path):
    tmp_path.chmod(0o700)
    with j.locked(tmp_path) as s:
        s.begin(plan())
        s.path.write_text(s.path.read_text().replace("prepared", "isolated"))
        with pytest.raises(ValueError, match="digest"):
            s.load()


def test_closed_session(tmp_path):
    tmp_path.chmod(0o700)
    with j.locked(tmp_path) as s:
        s.begin(plan())
    with pytest.raises(ValueError, match="closed"):
        s.advance("isolating")


def test_symlink_lock(tmp_path):
    tmp_path.chmod(0o700)
    (tmp_path / "release.lock").symlink_to("/dev/null")
    with pytest.raises(OSError):
        with j.locked(tmp_path):
            pass


def test_unsafe_directory(tmp_path):
    tmp_path.chmod(0o770)
    with pytest.raises(ValueError, match="owner-private"):
        with j.locked(tmp_path):
            pass
