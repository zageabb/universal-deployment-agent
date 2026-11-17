"""Offline tests for restrictive build execution and approval gating."""
from pathlib import Path
from unittest.mock import Mock, patch
import os

import pytest

from onboarding import OnboardingError
from onboarding_build import build_command, run_sandboxed_build
from onboarding_release import prepare_release


def prepared(tmp_path):
    sha = "a" * 40
    root = tmp_path / "staged"
    root.mkdir()
    stage = root / "demo-aaaaaaaaaaaa"
    stage.mkdir()
    (stage / "app.py").write_text("print('hello')\n")
    release_root = tmp_path / "releases"
    release_root.mkdir()
    release = prepare_release(
        {"application": "demo", "commit_sha": sha, "repository": "owner/demo",
         "staged_path": str(stage)}, root, release_root)
    output = tmp_path / "output"
    output.mkdir()
    return release, output


IMAGE = "docker.io/library/python@sha256:" + "a" * 64


def test_requires_pinned_builder_image(tmp_path):
    release, output = prepared(tmp_path)
    with pytest.raises(OnboardingError, match="pinned"):
        build_command(release, [["python", "-V"]], "python:3.12", output)


def test_builder_never_runs_shell_or_uses_network(tmp_path):
    release, output = prepared(tmp_path)
    tasks = build_command(release, [["python", "-m", "compileall", "."]], IMAGE, output)
    command = tasks[0]
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--pull=never" in command
    assert "/workspace:ro" in command
    assert command[-4:] == ["python", "-m", "compileall", "."]


def test_build_requires_separate_approval(tmp_path):
    release, output = prepared(tmp_path)
    with pytest.raises(OnboardingError, match="operator approval"):
        run_sandboxed_build(release, [["python", "-V"]], IMAGE, output)


def test_rejects_build_output_inside_release(tmp_path):
    release, output = prepared(tmp_path)
    with pytest.raises(OnboardingError, match="separate"):
        build_command(release, [["python", "-V"]], IMAGE, Path(release["release_path"]))


def test_rejects_tampered_release_before_build(tmp_path):
    release, output = prepared(tmp_path)
    (Path(release["release_path"]) / "app.py").write_text("tampered")
    with pytest.raises(OnboardingError, match="checksum"):
        build_command(release, [["python", "-V"]], IMAGE, output)


def test_build_refuses_root_execution(tmp_path):
    release, output = prepared(tmp_path)
    with patch("onboarding_build.os.geteuid", return_value=0):
        with pytest.raises(OnboardingError, match="root"):
            run_sandboxed_build(release, [["python", "-V"]], IMAGE, output,
                                approved=True)


def test_build_refuses_non_rootless_podman(tmp_path):
    release, output = prepared(tmp_path)
    with patch("onboarding_build.os.geteuid", return_value=1000), \
         patch("onboarding_build.shutil.which", return_value="/usr/bin/podman"):
        with pytest.raises(OnboardingError, match="not rootless"):
            run_sandboxed_build(release, [["python", "-V"]], IMAGE, output,
                                approved=True, runner=lambda *_a, **_kw:
                                Mock(returncode=0, stdout="false\n", stderr=""))


def test_successful_sandboxed_build_does_not_deploy(tmp_path):
    release, output = prepared(tmp_path)
    calls = []
    def runner(args, **kwargs):
        calls.append(args)
        if "info" in args:
            return Mock(returncode=0, stdout="true\n", stderr="")
        return Mock(returncode=0, stdout="ok", stderr="")
    with patch("onboarding_build.os.geteuid", return_value=1000), \
         patch("onboarding_build.shutil.which", return_value="/usr/bin/podman"):
        result = run_sandboxed_build(release, [["python", "-V"]], IMAGE, output,
                                     approved=True, runner=runner)
    assert result["status"] == "built_unactivated"
    assert result["service_started"] is False
    assert result["registry_modified"] is False
    assert len(calls) == 2
