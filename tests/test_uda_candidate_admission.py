import os
import pytest
from tools import uda_candidate_admission as c


def test_tree_detects_changed_bytes(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "module.py"
    path.write_text("first")
    before = c.tree(tmp_path)
    path.write_text("second")
    assert c.tree(tmp_path) != before


def test_tree_detects_addition(tmp_path):
    tmp_path.chmod(0o700)
    before = c.tree(tmp_path)
    (tmp_path / "new").write_text("data")
    assert c.tree(tmp_path) != before


def test_external_symlink_refused(tmp_path):
    tmp_path.chmod(0o700)
    (tmp_path / "external").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="symlink"):
        c.tree(tmp_path)


def test_permissions_refused(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "module.py"
    path.write_text("data")
    path.chmod(0o666)
    with pytest.raises(ValueError, match="permissions"):
        c.tree(tmp_path)


def test_hardlink_refused(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "module.py"
    path.write_text("data")
    os.link(path, tmp_path / "copy")
    with pytest.raises(ValueError, match="object"):
        c.tree(tmp_path)


def test_receipt_mismatch_refused_before_execution(monkeypatch, tmp_path):
    monkeypatch.setattr(c, "seal", lambda *args: {"tree_sha256": "changed"})
    monkeypatch.setattr(c.prep, "run", lambda *args: pytest.fail("Unverified interpreter executed"))
    with pytest.raises(ValueError, match="changed"):
        c.verify(tmp_path, tmp_path, {"tree_sha256": "original"})


def test_real_disposable_candidate(tmp_path, monkeypatch):
    # Exercise actual interpreter layout without downloading dependencies.
    import sys
    import subprocess
    destination = tmp_path / "venv-v2"
    destination.mkdir(mode=0o700)
    subprocess.run([sys._base_executable, "-m", "venv", "--copies", "--without-pip", str(destination)], check=True)
    before = c.tree(destination)
    assert len(before) == 64
    assert c.tree(destination) == before
