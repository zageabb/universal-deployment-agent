"""Disposable filesystem-only V2 unit adapter integration tests.

Never runs systemctl, starts OS services, changes Caddy or accesses production.
"""
from pathlib import Path
import tempfile
import uuid

import pytest
import yaml

from onboarding import OnboardingError
from onboarding_v2_multiservice import simulate_multiservice_release
from onboarding_v2_recovery_journal import DurableServiceJournal
from onboarding_v2_unit_sandbox import UnitSandboxAdapter

ROOT = Path(__file__).resolve().parents[1]
UNITS = {"web": "tender-web.service", "mailbox": "tender-mailbox.service"}
TEMPLATES = {"web": b"[Service]\nExecStart=/usr/bin/true\n",
             "mailbox": b"[Service]\nExecStart=/usr/bin/false\n"}


def manifest():
    return yaml.safe_load((ROOT / "examples/uda-v2-multi-service.yaml").read_text())


def fixture(tmp_path, *, fail_at=None, unhealthy=(), initial_running=()):
    root = tmp_path / "adapter"
    root.mkdir(mode=0o700)
    unit_folder = root / "units"
    unit_folder.mkdir(mode=0o700)
    initial = {name: b"[Service]\nDescription=prior-" + name.encode() + b"\n"
               for name in UNITS}
    for name, unit in UNITS.items():
        (unit_folder / unit).write_bytes(initial[name])
    active = set(initial_running)
    events = []

    def check(action, name):
        events.append(action + ":" + name)
        if fail_at == action + ":" + name:
            raise RuntimeError("injected failure")

    def start(name):
        active.add(name)
        check("start", name)

    def stop(name):
        active.discard(name)
        check("stop", name)

    def health(name, kind):
        check("health", name)
        return name not in unhealthy

    adapter = UnitSandboxAdapter(
        sandbox=root, unit_names=UNITS, rendered_units=TEMPLATES,
        is_running=lambda name: name in active,
        start_unit=start, stop_unit=stop, health_probe=health,
    )
    return root, adapter, initial, active, events


def execute(tmp_path, adapter):
    root = tmp_path / "journal"
    journal = DurableServiceJournal(root, str(uuid.uuid4()))
    result = simulate_multiservice_release(
        manifest(), adapter, journal=journal, simulation_only=True)
    return result, journal


def test_successful_multi_service_transaction_writes_only_isolated_units(tmp_path):
    root, adapter, previous, active, events = fixture(tmp_path)
    result, journal = execute(tmp_path, adapter)
    assert result.state == "healthy"
    assert active == {"web", "mailbox"}
    assert (root / "units" / UNITS["web"]).read_bytes() == TEMPLATES["web"]
    assert (root / "units" / UNITS["mailbox"]).read_bytes() == TEMPLATES["mailbox"]
    assert result.as_dict()["production_activation_allowed"] is False
    assert journal.recovery_status()["status"] == "healthy"
    assert events.index("start:web") < events.index("start:mailbox")


def test_failure_restores_previous_bytes_and_running_state(tmp_path):
    root, adapter, previous, active, events = fixture(
        tmp_path, unhealthy={"web"}, initial_running={"web"})
    result, journal = execute(tmp_path, adapter)
    assert result.state == "rolled_back"
    for name, unit in UNITS.items():
        assert (root / "units" / unit).read_bytes() == previous[name]
    assert active == {"web"}
    assert not result.pending_undo
    assert journal.recovery_status()["status"] == "rolled_back"


@pytest.mark.parametrize("failure", [
    "start:web", "start:mailbox", "health:web", "health:mailbox",
])
def test_partial_callback_failure_rolls_back_all_units(tmp_path, failure):
    root, adapter, previous, active, events = fixture(tmp_path, fail_at=failure)
    result, _ = execute(tmp_path, adapter)
    assert result.state == "rolled_back"
    assert active == set()
    assert all((root / "units" / unit).read_bytes() == previous[name]
               for name, unit in UNITS.items())


def test_optional_worker_health_failure_is_degraded(tmp_path):
    root, adapter, previous, active, events = fixture(
        tmp_path, unhealthy={"mailbox"})
    result, journal = execute(tmp_path, adapter)
    assert result.state == "degraded"
    assert result.degraded == ["mailbox"]
    assert active == {"web", "mailbox"}
    assert journal.recovery_status()["status"] == "degraded"


def test_only_declared_service_names_are_accepted(tmp_path):
    root, adapter, _, _, _ = fixture(tmp_path)
    with pytest.raises(OnboardingError, match="Undeclared"):
        adapter.capture_snapshot("other")


def test_rejects_unsafe_or_duplicate_unit_file_mapping(tmp_path):
    root = tmp_path / "isolated"
    root.mkdir(mode=0o700)
    kwargs = dict(sandbox=root, rendered_units=TEMPLATES,
                  is_running=lambda _: False, start_unit=lambda _: None,
                  stop_unit=lambda _: None, health_probe=lambda *_: True)
    for unit_names in [
        {"web": "../web.service", "mailbox": "mailbox.service"},
        {"web": "same.service", "mailbox": "same.service"},
        {"web": "--flag.service", "mailbox": "mailbox.service"},
    ]:
        with pytest.raises(OnboardingError):
            UnitSandboxAdapter(unit_names=unit_names, **kwargs)


def test_disallows_nonprivate_sandbox_and_symlink(tmp_path):
    root = tmp_path / "public"
    root.mkdir(mode=0o755)
    with pytest.raises(OnboardingError, match="private"):
        UnitSandboxAdapter(sandbox=root, unit_names=UNITS, rendered_units=TEMPLATES,
                           is_running=lambda _: False, start_unit=lambda _: None,
                           stop_unit=lambda _: None, health_probe=lambda *_: True)
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "linked"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(OnboardingError, match="trusted absolute"):
        UnitSandboxAdapter(sandbox=link, unit_names=UNITS, rendered_units=TEMPLATES,
                           is_running=lambda _: False, start_unit=lambda _: None,
                           stop_unit=lambda _: None, health_probe=lambda *_: True)


def test_symlinked_unit_and_hardlinked_unit_are_rejected(tmp_path):
    root, adapter, _, _, _ = fixture(tmp_path)
    dest = root / "units" / UNITS["web"]
    dest.unlink()
    dest.symlink_to(tmp_path / "outside")
    with pytest.raises(OnboardingError, match="symlink"):
        adapter.capture_snapshot("web")
    dest.unlink()
    external = root / "units" / "other"
    external.write_text("x")
    import os
    os.link(external, dest)
    with pytest.raises(OnboardingError, match="regular unique"):
        adapter.capture_snapshot("web")


def test_corrupted_unit_snapshot_refuses_restore(tmp_path):
    root, adapter, _, _, _ = fixture(tmp_path)
    snapshot = adapter.capture_snapshot("web")
    snapshot["sha256"] = "0" * 64
    with pytest.raises(OnboardingError, match="integrity"):
        adapter.restore("web", snapshot)


def test_sandbox_does_not_modify_root_outside_isolated_units(tmp_path):
    root, adapter, _, _, _ = fixture(tmp_path)
    outside = tmp_path / "sentinel"
    outside.write_text("untouched")
    result, _ = execute(tmp_path, adapter)
    assert result.state == "healthy"
    assert outside.read_text() == "untouched"
    assert not (root / "Caddyfile").exists()
    assert not (root / "registry.json").exists()
