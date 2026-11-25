import os
import pytest
from tools import uda_candidate_admission as c


def test_tree_detects_changed_bytes(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "module.py"
    path.write_text("first")
    path.chmod(0o600)
    before = c.tree(tmp_path)
    path.write_text("second")
    assert c.tree(tmp_path) != before


def test_tree_detects_addition(tmp_path):
    tmp_path.chmod(0o700)
    before = c.tree(tmp_path)
    (tmp_path / "new").write_text("data")
    (tmp_path / "new").chmod(0o600)
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
    path.chmod(0o600)
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
    subprocess.run([sys._base_executable, "-m", "venv", "--copies", "--without-pip", str(destination)], check=True, umask=0o077)
    c.prep.harden_new_tree(destination, c.prep.identity(destination))
    before = c.tree(destination)
    assert len(before) == 64
    assert c.tree(destination) == before


def test_preparation_subprocess_uses_private_umask(monkeypatch, tmp_path):
    from types import SimpleNamespace
    def run(*args, **kwargs):
        assert kwargs["umask"] == 0o077
        return SimpleNamespace(returncode=0, stdout="ok")
    monkeypatch.setattr(c.prep.subprocess, "run", run)
    assert c.prep.run("/usr/bin/python3", ["--version"], tmp_path) == "ok"


def test_harden_copied_permissions(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "copied-python"
    path.write_text("fixture")
    path.chmod(0o775)
    c.prep.harden_new_tree(tmp_path, c.prep.identity(tmp_path))
    assert path.stat().st_mode & 0o777 == 0o755
    assert len(c.tree(tmp_path)) == 64


def test_harden_does_not_follow_symlink(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.write_text("fixture")
    outside.chmod(0o666)
    (root / "link").symlink_to(outside)
    c.prep.harden_new_tree(root, c.prep.identity(root))
    assert outside.stat().st_mode & 0o777 == 0o666
    with pytest.raises(ValueError, match="symlink"):
        c.tree(root)
