"""Actual Ubuntu parser and injected-failure tests for V2 systemd review.

systemd-analyze verify parses disposable units; no systemd service is started.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from onboarding import OnboardingError
from onboarding_v2_systemd_verify import (
    VERIFY_TOOL, _runner, verify_disposable_unit_bundle,
)

SOURCE_SHA = "a" * 40


def bundle():
    units = {
        "uda-fixture-web.service": (
            "# UDA V2 REVIEW ARTIFACT ONLY\n"
            "[Unit]\nDescription=Fixture web\nAfter=basic.target\n"
            "[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
            "NoNewPrivileges=yes\nPrivateTmp=yes\n"
            "[Install]\nWantedBy=default.target\n"
        ),
        "uda-fixture-worker.service": (
            "# UDA V2 REVIEW ARTIFACT ONLY\n"
            "[Unit]\nDescription=Fixture worker\n"
            "After=uda-fixture-web.service\nRequires=uda-fixture-web.service\n"
            "[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
            "NoNewPrivileges=yes\nPrivateTmp=yes\n"
            "[Install]\nWantedBy=default.target\n"
        ),
    }
    order = list(units)
    hashes = {name: hashlib.sha256(text.encode()).hexdigest()
              for name, text in units.items()}
    evidence = {"application": "fixture", "commit_sha": SOURCE_SHA,
                "order": order, "unit_hashes": hashes}
    digest = hashlib.sha256(json.dumps(
        evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**evidence, "bundle_sha256": digest, "units": units,
            "status": "review_only", "approval_required": True,
            "deployment_allowed": False}


def private_root(tmp_path):
    root = tmp_path / "unit-check"
    root.mkdir(mode=0o700)
    return root


def test_parser_command_reviews_exact_unit_graph(tmp_path):
    root = private_root(tmp_path)
    calls = []
    def run(argv, *, cwd):
        calls.append((argv, cwd))
        assert argv[:2] == [VERIFY_TOOL, "verify"]
        assert len(argv) == 4
        assert all(Path(path).parent == cwd for path in argv[2:])
        return 0, ""
    result = verify_disposable_unit_bundle(bundle(), workspace=root, run=run)
    assert result["syntax_verified"] is True
    assert result["systemd_command"] == "verify"
    assert result["production_activation_allowed"] is False
    assert result["executed_unit_commands"] == 0
    assert len(calls) == 1
    assert all((root / "systemd-verify" / name).is_file()
               for name in bundle()["units"])


@pytest.mark.skipif(not Path(VERIFY_TOOL).exists(), reason="systemd-analyze is unavailable")
def test_real_ubuntu_systemd_analyze_accepts_disposable_units(tmp_path):
    root = private_root(tmp_path)
    result = verify_disposable_unit_bundle(bundle(), workspace=root)
    assert result["syntax_verified"] is True
    assert result["requires_ubuntu_service_acceptance"] is True


def test_nonzero_verifier_result_fails_acceptance_without_activation(tmp_path):
    root = private_root(tmp_path)
    result = verify_disposable_unit_bundle(
        bundle(), workspace=root,
        run=lambda argv, *, cwd: (1, "Unit syntax invalid\n"),
    )
    assert result["syntax_verified"] is False
    assert result["diagnostic_lines"] == 1
    assert result["production_activation_allowed"] is False


def test_modified_unit_text_rejected_before_any_verifier_call(tmp_path):
    root = private_root(tmp_path)
    doc = bundle()
    doc["units"]["uda-fixture-web.service"] += "ExecStart=/bin/sh\n"
    events = []
    with pytest.raises(OnboardingError, match="hash"):
        verify_disposable_unit_bundle(
            doc, workspace=root,
            run=lambda argv, *, cwd: events.append(argv),
        )
    assert events == []
    assert not (root / "systemd-verify").exists()


def test_unreviewed_unit_file_cannot_be_added(tmp_path):
    root = private_root(tmp_path)
    doc = bundle()
    doc["units"]["undeclared.service"] = "[Service]\nExecStart=/bin/true\n"
    with pytest.raises(OnboardingError):
        verify_disposable_unit_bundle(doc, workspace=root)


def test_nonprivate_directory_and_preexisting_work_dir_fail(tmp_path):
    root = private_root(tmp_path)
    root.chmod(0o755)
    with pytest.raises(OnboardingError, match="private"):
        verify_disposable_unit_bundle(bundle(), workspace=root)
    root.chmod(0o700)
    (root / "systemd-verify").mkdir()
    with pytest.raises(OnboardingError, match="already exists"):
        verify_disposable_unit_bundle(bundle(), workspace=root)


def test_systemd_analyze_wrapper_rejects_any_non_verify_process(tmp_path):
    root = private_root(tmp_path)
    for argv in (
        [VERIFY_TOOL, "security", "/tmp/fixture.service"],
        [VERIFY_TOOL, "verify", "/etc/systemd/system/ssh.service"],
        ["systemctl", "--user", "restart", "fixture.service"],
    ):
        with pytest.raises(OnboardingError):
            _runner(argv, cwd=root)


def test_verification_output_bounded_and_not_exposed(tmp_path):
    root = private_root(tmp_path)
    with pytest.raises(OnboardingError, match="output too large"):
        verify_disposable_unit_bundle(
            bundle(), workspace=root,
            run=lambda argv, *, cwd: (0, "TOKEN=SECRET_VALUE\n" * 5000),
        )


def test_a_second_run_must_use_a_new_private_workspace(tmp_path):
    root = private_root(tmp_path)
    verify_disposable_unit_bundle(
        bundle(), workspace=root, run=lambda argv, *, cwd: (0, ""),
    )
    with pytest.raises(OnboardingError, match="already exists"):
        verify_disposable_unit_bundle(
            bundle(), workspace=root, run=lambda argv, *, cwd: (0, ""),
        )
