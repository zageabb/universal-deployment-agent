"""Offline read-only Ubuntu evidence tests. Never invokes real systemctl."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from onboarding import OnboardingError
from onboarding_v2_ubuntu_preflight import UserSystemdInspector, inspect_live_graph
from onboarding_v2_ubuntu_preflight import _default_run

ROOT = Path(__file__).resolve().parents[1]


def manifest():
    d = yaml.safe_load((ROOT / "examples/uda-v2-multi-service.yaml").read_text())
    d["services"][0]["systemd_unit"] = "tender-web.service"
    d["services"][1]["systemd_unit"] = "tender-mailbox.service"
    d["lifecycle"] = {"owner": "tender-designer", "owned_units": [
        "tender-web.service", "tender-mailbox.service",
    ]}
    return d


def inspector(tmp_path: Path, *, include_mailbox=True, extra=False,
              mismatch=False, disclosure=None):
    checkout = tmp_path / "src"
    checkout.mkdir(exist_ok=True)
    entries = ["tender-web.service", *(
        ["tender-mailbox.service"] if include_mailbox else []
    ), *(["rogue-worker.service"] if extra else [])]
    calls = []

    def run(argv):
        calls.append(list(argv))
        assert argv[:2] == ["systemctl", "--user"]
        assert not {"stop", "start", "restart", "enable", "disable", "daemon-reload"} & set(argv)
        if argv[2] == "list-units":
            return "".join(f"{entry} loaded active running something\n" for entry in entries)
        assert argv[2] == "show"
        name = argv[-1]
        assert name in entries
        workdir = str(tmp_path / "different") if mismatch and name == "tender-web.service" else str(checkout)
        return (
            f"Id={name}\nLoadState=loaded\nActiveState=active\nSubState=running\n"
            f"WorkingDirectory={workdir}\nFragmentPath=/home/user/.config/systemd/user/{name}\n"
        )
    return checkout, UserSystemdInspector(run=run), calls


def test_reconciles_all_declared_units_with_readonly_calls(tmp_path):
    checkout, probe, calls = inspector(tmp_path)
    report = inspect_live_graph(manifest(), checkout, probe)
    assert report["ready_for_reconciliation"] is True
    assert not report["missing"] and not report["undeclared"]
    assert report["deployment_allowed"] is False
    assert report["write_operations"] == 0
    assert [x["unit"] for x in report["services"]] == [
        "tender-mailbox.service", "tender-web.service"]
    assert len(calls) == 3
    assert all(c[:2] == ["systemctl", "--user"] for c in calls)


def test_unregistered_mailbox_blocks_acceptance(tmp_path):
    checkout, probe, _ = inspector(tmp_path, include_mailbox=False)
    report = inspect_live_graph(manifest(), checkout, probe)
    assert report["ready_for_reconciliation"] is False
    assert report["missing"] == ["tender-mailbox.service"]
    assert any("Missing declared" in reason for reason in report["conflicts"])


def test_unexpected_repository_associated_unit_is_blocker(tmp_path):
    checkout, probe, _ = inspector(tmp_path, extra=True)
    report = inspect_live_graph(manifest(), checkout, probe)
    assert report["undeclared"] == ["rogue-worker.service"]
    assert report["ready_for_reconciliation"] is False


def test_service_workdir_mismatch_is_blocker(tmp_path):
    checkout, probe, _ = inspector(tmp_path, mismatch=True)
    report = inspect_live_graph(manifest(), checkout, probe)
    assert any("Unable to attest" in x for x in report["conflicts"])


def test_lifecycle_owner_must_match_declared_units(tmp_path):
    checkout, probe, _ = inspector(tmp_path)
    data = manifest()
    data["lifecycle"]["owned_units"].remove("tender-mailbox.service")
    report = inspect_live_graph(data, checkout, probe)
    assert any("owned_units differs" in x for x in report["conflicts"])


def test_missing_exact_systemd_unit_refuses_inspection(tmp_path):
    checkout, probe, calls = inspector(tmp_path)
    data = manifest()
    del data["services"][0]["systemd_unit"]
    with pytest.raises(OnboardingError, match="exact systemd_unit"):
        inspect_live_graph(data, checkout, probe)
    assert calls == []


def test_invalid_graph_fails_before_host_inventory(tmp_path):
    checkout, probe, calls = inspector(tmp_path)
    data = manifest()
    data["services"][0]["depends_on"] = ["mailbox"]
    with pytest.raises(OnboardingError, match="Invalid"):
        inspect_live_graph(data, checkout, probe)
    assert calls == []


@pytest.mark.parametrize("name", [
    "../escape.service", "--user.service", "/tmp/run.service", "fake.socket",
    "name.service\nrestart", "", 33,
])
def test_cannot_supply_unsafe_systemd_names(name):
    probe = UserSystemdInspector(run=lambda _: "")
    with pytest.raises(OnboardingError, match="Unsafe"):
        probe.details(name)


def test_systemctl_output_does_not_include_environment_values(tmp_path):
    _, probe, commands = inspector(tmp_path)
    data = probe.details("tender-web.service")
    assert "Environment" not in data
    assert "ExecStart" not in data
    assert all("--property=Id,LoadState,ActiveState,SubState,FragmentPath,WorkingDirectory" in cmd
               for cmd in commands)


def test_systemctl_rejects_unexpected_properties(tmp_path):
    checkout, _, _ = inspector(tmp_path)
    def bad(argv):
        return "Id=tender-web.service\nLoadState=loaded\nActiveState=active\nEnvironment=PASSWORD=secret\n"
    with pytest.raises(OnboardingError, match="Unexpected"):
        UserSystemdInspector(run=bad).details("tender-web.service")


def test_no_privileged_process_calls_in_default_adapter():
    with pytest.raises(OnboardingError, match="read-only"):
        _default_run(["systemctl", "--user", "stop", "anything.service"])


def test_checkout_must_be_trusted_directory(tmp_path):
    outside = tmp_path / "source"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    probe = UserSystemdInspector(run=lambda _: "")
    with pytest.raises(OnboardingError, match="trusted absolute"):
        inspect_live_graph(manifest(), linked, probe)


def test_simulated_systemd_output_limit(tmp_path):
    checkout = tmp_path / "src"
    checkout.mkdir()
    probe = UserSystemdInspector(run=lambda _: "A" * (128 * 1024 + 1))
    with pytest.raises(OnboardingError, match="response"):
        inspect_live_graph(manifest(), checkout, probe)


def test_exact_systemctl_allowlist_rejects_environment_disclosure():
    for argv in (
        ["systemctl", "--user", "show", "--property=Environment", "--", "demo.service"],
        ["systemctl", "--user", "restart", "--", "demo.service"],
        ["systemctl", "--user", "show", "--property=ExecStart", "--", "demo.service"],
        ["systemctl", "--user", "list-units", "--all", "--type=service", "--no-legend",
         "--plain", "--no-pager", "--", "demo.service"],
    ):
        with pytest.raises(OnboardingError, match="read-only"):
            _default_run(argv)


def test_inactive_service_with_wrong_workdir_is_not_accepted(tmp_path):
    checkout, _, _ = inspector(tmp_path)
    def run(argv):
        if argv[2] == "list-units":
            return ("tender-web.service loaded inactive dead -\\n"
                    "tender-mailbox.service loaded inactive dead -\\n")
        return (f"Id={argv[-1]}\\nLoadState=loaded\\nActiveState=inactive\\n"
                f"SubState=dead\\nWorkingDirectory={tmp_path}/wrong\\n"
                f"FragmentPath=/home/user/.config/systemd/user/{argv[-1]}\\n")
    report = inspect_live_graph(manifest(), checkout, UserSystemdInspector(run=run))
    assert report["ready_for_reconciliation"] is False
    assert len([x for x in report["conflicts"] if "Unable to attest" in x]) == 2

