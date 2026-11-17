"""V2 trusted rendering test fixtures; no systemd activation or live file writes."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import uuid

import pytest
import yaml

from onboarding import OnboardingError
from onboarding_release import prepare_release
from onboarding_v2_unit_renderer import render_reviewed_units

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def fixture(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    checkout = staging / ("tender-designer-" + SHA[:12])
    checkout.mkdir()
    (checkout / "app.py").write_text("pass\n")
    (checkout / "mailbox_daemon.py").write_text("pass\n")
    releases = tmp_path / "releases"
    releases.mkdir()
    release = prepare_release({
        "application": "tender-designer", "repository": "zageabb/tender_designer",
        "commit_sha": SHA, "staged_path": str(checkout),
    }, staging, releases)
    doc = yaml.safe_load((ROOT / "examples" / "uda-v2-multi-service.yaml").read_text())
    units = {"web": "tender-web.service", "mailbox": "tender-mailbox.service"}
    commands = {
        "web": ("/usr/bin/python3", "app.py"),
        "mailbox": ("/usr/bin/python3", "mailbox_daemon.py"),
    }
    for service in doc["services"]:
        service["systemd_unit"] = units[service["name"]]
        service["entrypoint"] = list(commands[service["name"]])
    env = {}
    for name in units:
        f = tmp_path / (name + ".env")
        f.write_text("TEST_KEY=test\n")
        f.chmod(0o600)
        env[name] = f
    return doc, Path(release["release_path"]), env, commands, units


def render(fixture_values, **overrides):
    doc, release, env, commands, units = fixture_values
    args = dict(release_path=release, source_commit_sha=SHA,
                environment_files=env, approved_entrypoints=commands,
                expected_units=units)
    args.update(overrides)
    return render_reviewed_units(doc, **args)


def test_reviewed_bundle_has_deterministic_sha_and_only_declared_units(tmp_path):
    values = fixture(tmp_path)
    result = render(values)
    another = render(values)
    assert result["bundle_sha256"] == another["bundle_sha256"]
    assert set(result["units"]) == {"tender-web.service", "tender-mailbox.service"}
    assert result["order"] == ["tender-web.service", "tender-mailbox.service"]
    assert result["deployment_allowed"] is False
    assert result["approval_required"] is True
    assert all("NoNewPrivileges=yes" in s and "ProtectSystem=strict" in s
               for s in result["units"].values())
    assert "After=tender-web.service" in result["units"]["tender-mailbox.service"]
    assert "Requires=tender-web.service" in result["units"]["tender-mailbox.service"]
    assert not (tmp_path / "tender-web.service").exists()


def test_bundle_does_not_contain_secret_environment_values(tmp_path):
    values = fixture(tmp_path)
    result = render(values)
    body = "\n".join(result["units"].values())
    assert "TEST_KEY=test" not in body
    assert "TEST_KEY" not in body
    assert "EnvironmentFile=" in body
    assert "% " not in body


@pytest.mark.parametrize("malicious", [
    ("sh", "-c", "rm -rf /"),
    ("/bin/bash", "-c", "true"),
    ("/usr/bin/env", "python3", "app.py"),
    ("python3", "app.py"),
    ("/usr/bin/python3", "-c", "print('hello')"),
])
def test_untrusted_commands_cannot_authorize_self(malicious, tmp_path):
    values = fixture(tmp_path)
    doc, release, env, commands, units = values
    doc["services"][0]["entrypoint"] = list(malicious)
    commands = dict(commands)
    commands["web"] = ("/usr/bin/python3", "app.py")
    with pytest.raises(OnboardingError, match="reviewed argv"):
        render(values, approved_entrypoints=commands)
    commands["web"] = tuple(malicious)
    if malicious[0] != "/usr/bin/python3":
        with pytest.raises(OnboardingError, match="allowlist"):
            render(values, approved_entrypoints=commands)


def test_unit_files_fail_on_missing_release_sha(tmp_path):
    values = fixture(tmp_path)
    with pytest.raises(OnboardingError):
        render(values, source_commit_sha="b" * 40)


def test_unit_source_tampering_blocks_render(tmp_path):
    values = fixture(tmp_path)
    (values[1] / "app.py").write_text("changed")
    with pytest.raises(OnboardingError, match="checksum"):
        render(values)


def test_no_undeclared_or_duplicate_units(tmp_path):
    values = fixture(tmp_path)
    doc, release, env, commands, units = values
    units = dict(units)
    units["mailbox"] = "tender-web.service"
    with pytest.raises(OnboardingError, match="identity"):
        render(values, expected_units=units)


def test_disallow_missing_environment_file_and_exposed_permissions(tmp_path):
    values = fixture(tmp_path)
    env = dict(values[2])
    env["web"].chmod(0o644)
    with pytest.raises(OnboardingError, match="private"):
        render(values, environment_files=env)


def test_reject_manifest_unit_mismatch(tmp_path):
    values = fixture(tmp_path)
    values[0]["services"][0]["systemd_unit"] = "another.service"
    with pytest.raises(OnboardingError, match="identity differs"):
        render(values)


def test_environment_path_cannot_be_symlink(tmp_path):
    values = fixture(tmp_path)
    env = dict(values[2])
    link = tmp_path / "symlink.env"
    link.symlink_to(env["web"])
    env["web"] = link
    with pytest.raises(OnboardingError, match="unlinked"):
        render(values, environment_files=env)


def test_systemd_injection_newline_and_percent_escaping(tmp_path):
    values = fixture(tmp_path)
    doc, release, env, commands, units = values
    doc["services"][0]["entrypoint"] = ["/usr/bin/python3", "a%\nb"]
    commands = dict(commands)
    commands["web"] = ("/usr/bin/python3", "a%\nb")
    with pytest.raises(OnboardingError, match="argv"):
        render(values, approved_entrypoints=commands)
    doc["services"][0]["entrypoint"] = ["/usr/bin/python3", "percent%value"]
    commands["web"] = ("/usr/bin/python3", "percent%value")
    rendered = render(values, approved_entrypoints=commands)
    assert "percent%%value" in rendered["units"]["tender-web.service"]


def test_reject_unverified_working_directory(tmp_path):
    values = fixture(tmp_path)
    values[0]["services"][0]["working_dir"] = "missing"
    with pytest.raises(OnboardingError, match="working directory"):
        render(values)


def test_platform_and_container_manifests_cannot_reach_unit_renderer(tmp_path):
    values = fixture(tmp_path)
    values[0]["deployment"]["strategy"] = "containers"
    with pytest.raises(OnboardingError):
        render(values)
