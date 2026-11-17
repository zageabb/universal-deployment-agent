"""V2-002: pinned-source schema dispatch and non-activating review."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import json

import pytest
import yaml

from onboarding import OnboardingError, validate_manifest
from onboarding_v2 import parse_versioned_manifest, preview_v2

FIXTURE = Path(__file__).resolve().parents[1] / "examples/uda-v2-multi-service.yaml"


def v2_document():
    return yaml.safe_load(FIXTURE.read_text())


def v2_preview():
    return {
        "repository": "zageabb/tender_designer", "branch": "main",
        "commit_sha": "a" * 40, "manifest": v2_document(),
    }


def test_v2_source_manifest_generates_readonly_graph():
    document = v2_document()
    parsed = parse_versioned_manifest(yaml.safe_dump(document).encode())
    assert parsed["schema_version"] == 2
    output = preview_v2(v2_preview(), {"applications": []})
    assert output["operation"] == "v2_readonly_preview"
    assert output["staging_allowed"] is False
    assert output["execution_allowed"] is False
    assert [x["name"] for x in output["workloads"]] == ["web", "mailbox"]
    assert output["health"]["optional"] == ["mailbox"]
    assert output["proxy"]["upstream"] == "web"


def test_v1_is_backward_compatible_and_small_limit():
    doc = {
        "schema_version": 1,
        "application": {"name": "demo"},
        "runtime": {"type": "python"},
        "service": {"entrypoint": ["python", "app.py"]},
    }
    raw = yaml.safe_dump(doc).encode()
    assert parse_versioned_manifest(raw) == validate_manifest(doc)
    with pytest.raises(OnboardingError, match="32 KiB"):
        parse_versioned_manifest(raw + b" " * (33 * 1024))


@pytest.mark.parametrize("version", [0, 3, -1, True, "2", None])
def test_unknown_version_fails_closed(version):
    doc = v2_document()
    doc["schema_version"] = version
    with pytest.raises(OnboardingError, match="schema_version"):
        parse_versioned_manifest(yaml.safe_dump(doc).encode())


def test_v2_unknown_key_fails_closed():
    doc = v2_document()
    doc["deployment"]["privileged_shell"] = "sudo chmod -R 777 /"
    with pytest.raises(OnboardingError, match="Invalid v2"):
        parse_versioned_manifest(yaml.safe_dump(doc).encode())


def test_v2_source_identity_must_match_selected_branch():
    preview = v2_preview()
    preview["manifest"]["source"]["branch"] = "other"
    with pytest.raises(OnboardingError, match="source.branch"):
        preview_v2(preview, {"applications": []})


def test_v2_preview_detects_existing_registry_without_mutation():
    registry = {"applications": [
        {"name": "tender-designer", "port": 5050, "service_unit": "web.service"},
        {"name": "other", "port": 5200},
    ]}
    snapshot = json.dumps(registry, sort_keys=True)
    preview = v2_preview()
    preview["manifest"]["services"][0]["port"] = 5200
    output = preview_v2(preview, registry)
    assert any("already exists" in x for x in output["conflicts"])
    assert any("Port 5200" in x for x in output["conflicts"])
    assert json.dumps(registry, sort_keys=True) == snapshot


def test_v2_preview_does_not_emit_entrypoints_build_commands_or_secret_values():
    preview = v2_preview()
    preview["manifest"]["environment"] = {"required": ["VERY_SECRET_TOKEN"]}
    preview["manifest"]["services"][0]["entrypoint"] = [
        "python", "app.py", "--secret=some-actual-credential"]
    output = preview_v2(preview, {"applications": []})
    serialised = json.dumps(output)
    assert "some-actual-credential" not in serialised
    assert "entrypoint" not in serialised
    assert "VERY_SECRET_TOKEN" in serialised


def test_v2_preview_dashboard_never_issues_stage_ticket(tmp_path):
    from dashboard import create_app
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"dashboard_token": "secret", "applications": []}))
    client = create_app(config).test_client()
    headers = {"Authorization": "Basic YWRtaW46c2VjcmV0"}
    with patch("dashboard.inspect_repo", return_value=v2_preview()), (
            patch("dashboard.prepare_plan", side_effect=AssertionError("v1 plan called"))), (
            patch("dashboard.issue_ticket", side_effect=AssertionError("stage ticket issued"))):
        response = client.post("/onboarding/preview", headers=headers, data={
            "csrf_token": client.application.config["CSRF_TOKEN"],
            "repository_url": "https://github.com/zageabb/tender_designer",
            "branch": "main",
        })
    assert response.status_code == 200
    assert b"V2 deployment graph" in response.data
    assert b"Approve source staging only" not in response.data
    assert b"Installation unavailable" in response.data


def test_dashboard_v2_remains_csrf_and_basic_auth_protected(tmp_path):
    from dashboard import create_app
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"dashboard_token": "secret", "applications": []}))
    client = create_app(cfg).test_client()
    assert client.post("/onboarding/preview").status_code == 401
    assert client.post("/onboarding/preview", headers={
        "Authorization": "Basic YWRtaW46c2VjcmV0"}, data={
        "repository_url": "https://github.com/zageabb/demo", "branch": "main"
    }).status_code == 403
