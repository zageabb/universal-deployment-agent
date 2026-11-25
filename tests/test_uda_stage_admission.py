"""Admission guard tests; no actual pip or systemd commands."""
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
from tools import uda_stage_admission as a
from tools.uda_runtime_integrity import ROOT, payload_paths


@pytest.fixture
def stage(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir(mode=0o700)
    for name, source in payload_paths(ROOT).items():
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        dest.chmod(0o644)
    venv = root / "runtime/venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin/python").write_text("stub")
    (venv / "bin/python").chmod(0o700)
    (venv / "pyvenv.cfg").write_text("fixture")
    return root


def stub(stage, monkeypatch, fail=None, prefix=None):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert args[1:3] == ["-I", "-B"]
        assert kwargs["env"]["HOME"] != str(Path.home())
        assert "PYTHONPATH" not in kwargs["env"]
        if len(calls) == fail:
            return SimpleNamespace(returncode=1, stdout="")
        output = (str(prefix or stage / "runtime/venv") if len(calls) == 1
                  else '{"smoke":"PASS"}' if len(calls) == 3 else "")
        return SimpleNamespace(returncode=0, stdout=output)
    monkeypatch.setattr(a.subprocess, "run", run)
    return calls


def test_acceptance_runs_three_isolated_checks(stage, monkeypatch):
    calls = stub(stage, monkeypatch)
    result = a.accept(stage)
    assert len(calls) == 3
    assert result["pip_check_passed"]
    assert not result["production_upgrade_authorized"]


def test_tamper_refused_before_execution(stage, monkeypatch):
    calls = stub(stage, monkeypatch)
    (stage / "runtime/dashboard.py").write_text("tampered")
    with pytest.raises(ValueError, match="differs"):
        a.accept(stage)
    assert calls == []


def test_wrong_prefix_refused(stage, monkeypatch):
    calls = stub(stage, monkeypatch, prefix="/usr")
    with pytest.raises(ValueError, match="not bound"):
        a.accept(stage)
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [2, 3])
def test_failed_dependency_or_smoke_refused(stage, monkeypatch, failure):
    calls = stub(stage, monkeypatch, fail=failure)
    with pytest.raises(RuntimeError, match="subprocess failed"):
        a.accept(stage)
    assert len(calls) == failure


def test_missing_venv_refused(stage, monkeypatch):
    calls = stub(stage, monkeypatch)
    (stage / "runtime/venv/pyvenv.cfg").unlink()
    with pytest.raises(ValueError, match="environment missing"):
        a.accept(stage)
    assert calls == []
