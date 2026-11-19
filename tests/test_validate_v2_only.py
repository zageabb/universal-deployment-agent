"""Disposable Git fixture coverage for the read-only V2-only validator."""
from __future__ import annotations

import subprocess

import yaml

from tools.validate_v2_only import inspect


SCHEMA = {
    "type": "object",
    "required": ["schema_version", "application", "deployment"],
    "properties": {
        "schema_version": {"const": 2},
        "application": {"type": "object"},
        "deployment": {"type": "object"},
    },
}


def fixture(tmp_path, *, commands=None, auto_update=False, repository=None):
    path = tmp_path / "research-core"
    path.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(path), *args], check=True,
                              capture_output=True, text=True).stdout
    git("init")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    manifest = {
        "schema_version": 2,
        "application": {"name": "research-core", "kind": "library"},
        "source": {"repository": repository or "zageabb/research-core"},
        "deployment": {"strategy": "library", "approval": "explicit",
                       "auto_update": auto_update, "rollback": False},
    }
    if commands is not None:
        manifest["builds"] = [{
            "name": "wheel", "toolchain": "python",
            "working_dir": ".", "commands": commands,
        }]
    (path / "uda.v2.yaml").write_text(yaml.safe_dump(manifest))
    git("add", ".")
    git("commit", "-m", "fixture")
    git("branch", "feature/uda-v2-review")
    return path


def test_valid_manifest_stays_review_until_host_acceptance(tmp_path):
    result = inspect(fixture(tmp_path), SCHEMA, lambda value: None)
    assert result["status"] == "REVIEW"
    assert not result["errors"]
    assert result["warnings"]


def test_activation_policy_violation_fails(tmp_path):
    result = inspect(fixture(tmp_path, auto_update=True), SCHEMA, lambda value: None)
    assert result["status"] == "FAIL"
    assert any("POLICY:" in item for item in result["errors"])


def test_missing_source_file_fails(tmp_path):
    result = inspect(fixture(tmp_path, commands=[["pip", "install", "-r", "missing.txt"]]),
                     SCHEMA, lambda value: None)
    assert result["status"] == "FAIL"
    assert any("missing requirements" in item for item in result["errors"])


def test_bad_repository_identity_fails(tmp_path):
    result = inspect(fixture(tmp_path, repository="zageabb/other"),
                     SCHEMA, lambda value: None)
    assert result["status"] == "FAIL"
    assert "SOURCE:repository identity mismatch" in result["errors"]


def test_semantic_fail_is_not_ignored(tmp_path):
    def reject(_doc):
        raise ValueError("bad graph")
    result = inspect(fixture(tmp_path), SCHEMA, reject)
    assert result["status"] == "FAIL"
    assert "SEMANTIC:bad graph" in result["errors"]


# These cases use the real canonical JSON Schema + semantic validator,
# not the intentionally minimal fixture schema used above.
def test_canonical_library_requires_isolated_install_verification():
    import pytest
    from uda_manifest_v2_validate import validate

    doc = {
        "schema_version": 2,
        "application": {"name": "research-core", "kind": "library"},
        "deployment": {"strategy": "library", "approval": "explicit",
                       "auto_update": False, "rollback": False},
        "lifecycle": {"owner": "research-core"},
        "library": {
            "isolation": "package-artifact",
            "verify_commands": [["python3", "-m", "pytest", "-q", "tests"]],
        },
    }
    assert validate(doc)["deployment_allowed"] is False
    invalid = {key: value for key, value in doc.items() if key != "library"}
    with pytest.raises(ValueError, match="Library deployment requires isolated"):
        validate(invalid)


def test_canonical_persistent_volume_requires_lifecycle_owner():
    import copy
    import pytest
    from uda_manifest_v2_validate import validate

    doc = {
        "schema_version": 2,
        "application": {"name": "sidecar", "kind": "web"},
        "containers": [{
            "name": "sidecar",
            "build": {"context": ".", "dockerfile": "Dockerfile",
                      "provenance": "pinned-source-commit"},
            "volumes": [{
                "name": "sidecar-data", "kind": "named", "mount_path": "/data",
                "owner": "sidecar", "preserve_data": True,
                "backup_policy": "manual-review",
                "restore_policy": "manual-recovery",
            }],
            "health": {"type": "process"},
        }],
        "proxy": {"enabled": True, "upstream": "sidecar",
                  "canonical_path": "/apps/sidecar/", "authentication": "uda"},
        "deployment": {"strategy": "containers", "approval": "explicit",
                       "auto_update": False, "rollback": False},
        "lifecycle": {"owner": "sidecar"},
    }
    assert validate(doc)["deployment_allowed"] is False
    unsafe = copy.deepcopy(doc)
    del unsafe["containers"][0]["volumes"][0]["owner"]
    with pytest.raises(ValueError, match="Persistent volume requires lifecycle owner"):
        validate(unsafe)


def test_every_v2_only_repo_has_explicit_unresolved_review_gates():
    from tools.validate_v2_only import REPOS, REVIEW_GATES

    assert set(REVIEW_GATES) == set(REPOS)
    assert all(REVIEW_GATES[repo] for repo in REPOS)


def test_report_retains_concrete_review_gates_even_after_source_checks(tmp_path):
    from tools.validate_v2_only import REVIEW_GATES

    result = inspect(fixture(tmp_path), SCHEMA, lambda value: None)
    assert result["status"] == "REVIEW"
    assert not result["errors"]
    for code in REVIEW_GATES["research-core"]:
        assert "REVIEW_GATE:" + code in result["warnings"]
