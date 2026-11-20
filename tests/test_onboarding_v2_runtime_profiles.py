"""V2 Python virtualenv provenance and review-only unit rendering tests.

Simulated interpreters are never executed. The source tree is created in tmp.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import os

import pytest
import yaml

from onboarding import OnboardingError
from onboarding_release import prepare_release
from onboarding_v2_runtime_profiles import review_python_venv
from onboarding_v2_unit_renderer import render_reviewed_units
from onboarding_v2_approval import issue_review_attestation, review_attestation

SOURCE_SHA = "a" * 40
ROOT = Path(__file__).resolve().parents[1]


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup(tmp_path):
    source_root = tmp_path / "staging"
    source_root.mkdir()
    source = source_root / ("tender-designer-" + SOURCE_SHA[:12])
    source.mkdir()
    (source / "app.py").write_text("pass\n")
    (source / "mailbox_daemon.py").write_text("pass\n")
    release_root = tmp_path / "releases"
    release_root.mkdir()
    release = prepare_release({
        "application": "tender-designer", "repository": "zageabb/tender_designer",
        "commit_sha": SOURCE_SHA, "staged_path": str(source),
    }, source_root, release_root)
    manifest = yaml.safe_load((ROOT / "examples/uda-v2-multi-service.yaml").read_text())
    unit_names = {"web": "tender-web.service", "mailbox": "tender-mailbox.service"}
    commands = {"web": (".venv/bin/python", "app.py"),
                "mailbox": ("/usr/bin/python3", "mailbox_daemon.py")}
    env = {}
    for name, unit in unit_names.items():
        file = tmp_path / (unit + ".env")
        file.write_text("SESSION_SECRET=do-not-show\n")
        file.chmod(0o600)
        env[name] = file
    for svc in manifest["services"]:
        svc["systemd_unit"] = unit_names[svc["name"]]
        svc["entrypoint"] = list(commands[svc["name"]])

    # Dummy executable is not run. It simulates independently provisioned
    # interpreter bytes, separately from immutable source release files.
    approved = tmp_path / "independently-reviewed-python"
    approved.write_bytes(b"trusted-test-executable-bytes")
    approved.chmod(0o700)
    venv = tmp_path / "python-runtime" / ".venv"
    (venv / "bin").mkdir(parents=True, mode=0o700)
    venv.chmod(0o700)
    (venv / "bin").chmod(0o700)
    (venv / "bin" / "python").symlink_to(approved)
    cfg = venv / "pyvenv.cfg"
    cfg.write_text("include-system-site-packages = false\nversion = 3.12\n")
    cfg.chmod(0o600)
    profile = {"type": "python-venv", "venv_root": venv,
               "approved_python": approved, "python_sha256": file_sha(approved),
               "config_sha256": file_sha(cfg), "source_commit": SOURCE_SHA}
    args = dict(release_path=Path(release["release_path"]), source_commit_sha=SOURCE_SHA,
                environment_files=env, approved_entrypoints=commands,
                expected_units=unit_names, runtime_profiles={"web": profile})
    return manifest, args, profile


def test_reviewed_virtualenv_renders_exact_verified_interpreter(tmp_path):
    manifest, args, profile = setup(tmp_path)
    evidence = review_python_venv(profile, release_commit=SOURCE_SHA)
    assert evidence["can_execute"] is False
    result = render_reviewed_units(manifest, **args)
    text = result["units"]["tender-web.service"]
    assert str(profile["venv_root"] / "bin" / "python") in text
    assert "SESSION_SECRET" not in text
    assert result["deployment_allowed"] is False
    assert result["approval_required"] is True
    assert result["status"] == "review_only"


def test_runtime_digest_changes_bundle_digest(tmp_path):
    manifest, args, profile = setup(tmp_path)
    before = render_reviewed_units(manifest, **args)["bundle_sha256"]
    second = tmp_path / "other-approved-python"
    second.write_bytes(b"another-approved-interpreter")
    second.chmod(0o700)
    (profile["venv_root"] / "bin" / "python").unlink()
    (profile["venv_root"] / "bin" / "python").symlink_to(second)
    profile["approved_python"] = second
    profile["python_sha256"] = file_sha(second)
    after = render_reviewed_units(manifest, **args)["bundle_sha256"]
    assert before != after


def test_runtime_interpreter_drift_is_rejected(tmp_path):
    manifest, args, profile = setup(tmp_path)
    profile["approved_python"].write_bytes(b"modified-executable")
    with pytest.raises(OnboardingError, match="Python digest mismatch"):
        render_reviewed_units(manifest, **args)


def test_virtualenv_config_drift_rejected(tmp_path):
    manifest, args, profile = setup(tmp_path)
    (profile["venv_root"] / "pyvenv.cfg").write_text("home = /wrong\n")
    with pytest.raises(OnboardingError, match="configuration digest"):
        render_reviewed_units(manifest, **args)


def test_virtualenv_symlink_cannot_switch_target(tmp_path):
    manifest, args, profile = setup(tmp_path)
    (profile["venv_root"] / "bin" / "python").unlink()
    (profile["venv_root"] / "bin" / "python").symlink_to("/bin/sh")
    with pytest.raises(OnboardingError, match="target differs"):
        render_reviewed_units(manifest, **args)


def test_virtualenv_rejects_wrong_commit_even_with_correct_binary(tmp_path):
    manifest, args, profile = setup(tmp_path)
    profile["source_commit"] = "b" * 40
    with pytest.raises(OnboardingError, match="reviewed release commit"):
        render_reviewed_units(manifest, **args)


def test_virtualenv_rejects_public_writable_directory(tmp_path):
    manifest, args, profile = setup(tmp_path)
    profile["venv_root"].chmod(0o777)
    with pytest.raises(OnboardingError, match="group/world writable"):
        render_reviewed_units(manifest, **args)


def test_profile_must_match_manifest_runtime_kind(tmp_path):
    manifest, args, profile = setup(tmp_path)
    manifest["services"][0]["runtime"] = "node"
    with pytest.raises(OnboardingError, match="Python virtualenv"):
        render_reviewed_units(manifest, **args)


def test_missing_external_profile_is_not_implicit_permission(tmp_path):
    manifest, args, profile = setup(tmp_path)
    args["runtime_profiles"] = {}
    with pytest.raises(OnboardingError, match="allowlist"):
        render_reviewed_units(manifest, **args)


def test_external_runtime_cannot_be_referenced_by_unrelated_service(tmp_path):
    manifest, args, profile = setup(tmp_path)
    args["runtime_profiles"] = {"other": profile}
    with pytest.raises(OnboardingError, match="Unexpected reviewed runtime profile"):
        render_reviewed_units(manifest, **args)


def test_python_c_argument_and_shell_execution_remain_rejected(tmp_path):
    manifest, args, profile = setup(tmp_path)
    manifest["services"][0]["entrypoint"] = [".venv/bin/python", "-c", "import os"]
    args["approved_entrypoints"]["web"] = tuple(manifest["services"][0]["entrypoint"])
    with pytest.raises(OnboardingError, match="local script"):
        render_reviewed_units(manifest, **args)


def test_runtime_profile_not_serialized_into_unit_file(tmp_path):
    manifest, args, profile = setup(tmp_path)
    result = render_reviewed_units(manifest, **args)
    text = "\n".join(result["units"].values())
    assert "python_sha256" not in text
    assert "config_sha256" not in text
    assert "source_commit" not in text


def test_runtime_change_invalidates_previous_signed_approval(tmp_path):
    manifest, args, profile = setup(tmp_path)
    previous = render_reviewed_units(manifest, **args)
    key = b"independent-review-authority-32bytes-test-only"
    token = issue_review_attestation(previous, operator="reviewer@example.com",
                                     signing_key=key, now=20000)
    replacement = tmp_path / "new-reviewed-python"
    replacement.write_bytes(b"changed-runtime-build")
    replacement.chmod(0o700)
    (profile["venv_root"] / "bin" / "python").unlink()
    (profile["venv_root"] / "bin" / "python").symlink_to(replacement)
    profile["approved_python"] = replacement
    profile["python_sha256"] = file_sha(replacement)
    updated = render_reviewed_units(manifest, **args)
    assert updated["bundle_sha256"] != previous["bundle_sha256"]
    store = tmp_path / "approvals"
    store.mkdir(mode=0o700)
    with pytest.raises(OnboardingError, match="scope differs"):
        review_attestation(updated, token, operator="reviewer@example.com",
                           signing_key=key, receipt_store=store, now=20001)
    assert not list(store.iterdir())


def test_runtime_evidence_hash_is_checked_by_approval_verifier(tmp_path):
    manifest, args, _ = setup(tmp_path)
    bundle = render_reviewed_units(manifest, **args)
    assert set(bundle["runtime_hashes"]) == {"tender-web.service"}
    altered = deepcopy(bundle)
    altered["runtime_hashes"]["tender-web.service"] = "a" * 64
    with pytest.raises(OnboardingError, match="digest mismatch"):
        issue_review_attestation(altered, operator="reviewer@example.com",
                                 signing_key=b"independent-review-authority-32bytes-test-only",
                                 now=20000)
