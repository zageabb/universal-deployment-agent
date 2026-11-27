"""Exercise the real installer with a disposable HOME and fake dependency builder.

No live systemd, pip/network or production configuration is used.
"""
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def lab(tmp_path):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    parent = tmp_path / "staging"
    parent.mkdir(mode=0o700)
    commands = tmp_path / "commands"
    commands.mkdir()
    log = tmp_path / "systemctl-called"
    (commands / "systemctl").write_text('#!/bin/sh\ntouch "$TEST_SYSTEMCTL_LOG"\nexit 99\n')
    (commands / "python3").write_text(
        '#!/bin/sh\n[ "$1" = "-m" ] && [ "$2" = "venv" ] || exit 99\n'
        'mkdir -p "$3/bin"\nprintf "#!/bin/sh\\nexit 0\\n" > "$3/bin/pip"\nchmod +x "$3/bin/pip"\n')
    for path in commands.iterdir():
        path.chmod(0o700)
    env = {**os.environ, "HOME": str(home), "XDG_DATA_HOME": str(home / ".local/share"),
           "XDG_CONFIG_HOME": str(home / ".config"), "PATH": str(commands) + ":" + os.environ["PATH"],
           "TEST_SYSTEMCTL_LOG": str(log)}
    runtime = home / ".local/share/deployment-agent"
    runtime.mkdir(parents=True)
    (runtime / "sentinel").write_text("known good")
    config = home / ".config/deployment-agent"
    config.mkdir(parents=True)
    (config / "config.json").write_text("existing config")
    return home, parent, runtime, config, log, env


def invoke(lab, *args):
    return subprocess.run(["sh", str(ROOT / "install.sh"), *map(str, args)],
                          env=lab[-1], capture_output=True, text=True, timeout=30)


def test_stage_only_copies_runtime_without_service_actions(lab):
    home, parent, runtime, config, log, env = lab
    target = parent / "candidate"
    result = invoke(lab, "--stage-only", target)
    assert result.returncode == 0, result.stderr
    assert (target / "runtime/dashboard.py").is_file()
    assert (target / "runtime/venv/bin/pip").is_file()
    assert (target / "units/deployment-agent.timer").is_file()
    assert (target / "runtime/templates/approvals.html").is_file()
    assert (target / "config/config.json").is_file()
    assert (target.stat().st_mode & 0o777) == 0o700
    assert not log.exists()
    assert (runtime / "sentinel").read_text() == "known good"
    assert (config / "config.json").read_text() == "existing config"
    assert not (runtime / "dashboard.py").exists()


@pytest.mark.parametrize("args", [(), ("--install-inactive",), ("--unknown",)])
def test_existing_installation_cannot_be_changed(lab, args):
    assert invoke(lab, *args).returncode == 2
    assert not lab[4].exists()
    assert not (lab[2] / "dashboard.py").exists()


def test_existing_stage_refused(lab):
    assert invoke(lab, "--stage-only", lab[1]).returncode != 0
    assert not lab[4].exists()


def test_stage_under_live_runtime_refused(lab):
    lab[2].chmod(0o700)
    target = lab[2] / "candidate"
    assert invoke(lab, "--stage-only", target).returncode == 2
    assert not target.exists()


def test_nonprivate_parent_refused(lab):
    lab[1].chmod(0o755)
    assert invoke(lab, "--stage-only", lab[1] / "candidate").returncode == 2
    assert not lab[4].exists()
