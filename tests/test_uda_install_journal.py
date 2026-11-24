"""Real SIGKILL boundaries in synthetic private labs."""
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from tools import uda_install_journal as j


@pytest.fixture
def lab(tmp_path):
    root = tmp_path / "uda-journal-lab-test"
    root.mkdir(mode=0o700)
    j.init_lab(root)
    return root


def child(lab, action, crash):
    return subprocess.run([sys.executable, j.__file__, action, "--lab", str(lab),
                           "--crash", crash], timeout=20, capture_output=True)


def restored(lab):
    assert (lab / "runtime/existing.py").read_bytes() == j.OLD
    assert (lab / "runtime/existing.py").stat().st_mode & 0o777 == 0o640
    assert not (lab / "runtime/new.py").exists()
    assert (lab / "runtime/unmanaged").read_bytes() == b"preserve"
    assert j.review(lab)["phase"] == "rolled_back"


@pytest.mark.parametrize("boundary", ["before:existing.py", "after:existing.py",
                                      "before:new.py", "after:new.py"])
def test_sigkill_install_recovery(lab, boundary):
    assert child(lab, "install", boundary).returncode == -signal.SIGKILL
    assert j.review(lab)["recovery_required"]
    with pytest.raises(ValueError, match="Existing transaction"):
        j.install(lab)
    j.recover(lab)
    restored(lab)


@pytest.mark.parametrize("boundary", ["restore:existing.py", "restore:new.py"])
def test_sigkill_during_recovery(lab, boundary):
    assert child(lab, "install", "after:new.py").returncode == -signal.SIGKILL
    assert child(lab, "recover", boundary).returncode == -signal.SIGKILL
    assert j.review(lab)["recovery_required"]
    j.recover(lab)
    restored(lab)


def test_success(lab):
    j.install(lab)
    assert j.review(lab)["phase"] == "complete"
    assert not j.review(lab)["recovery_required"]
    with pytest.raises(ValueError, match="not interrupted"):
        j.recover(lab)


def test_bad_backup_refused(lab):
    assert child(lab, "install", "after:new.py").returncode == -signal.SIGKILL
    (lab / "backup/existing.py").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Backup integrity"):
        j.recover(lab)
    assert (lab / "runtime/new.py").read_bytes() == j.NEW


def test_unknown_runtime_refused(lab):
    assert child(lab, "install", "after:new.py").returncode == -signal.SIGKILL
    (lab / "runtime/existing.py").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="Unexpected runtime"):
        j.recover(lab)
    assert (lab / "runtime/new.py").read_bytes() == j.NEW


def test_lock_refuses_overlap(lab):
    with j.locked(lab):
        with pytest.raises(BlockingIOError):
            j.install(lab)
    assert not (lab / "journal.json").exists()
