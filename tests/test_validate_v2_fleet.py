"""Independent runner tests; all repositories and Git objects are disposable fixtures."""
from __future__ import annotations

import subprocess

from tools.validate_v2_fleet import check_parity, load_revision_file


def _pair():
    old = {
        "application": {"name": "sample"},
        "source": {"branch": "main"},
        "runtime": {"type": "python", "working_dir": "."},
        "service": {"entrypoint": ["python", "app.py"], "port": 5555, "health_path": "/"},
        "build": {"commands": []}, "proxy": {"enabled": False},
        "environment": {"required": []},
        "deployment": {"rollback": True, "github_reporting": False},
    }
    new = {
        "application": {"name": "sample"}, "source": {"branch": "main"},
        "services": [{"runtime": "python", "working_dir": ".",
                      "entrypoint": ["python", "app.py"], "port": 5555, "health": {"path": "/"}}],
        "proxy": {"enabled": False}, "environment": {"required": []},
        "deployment": {"strategy": "systemd", "rollback": True,
                       "github_reporting": False, "approval": "explicit",
                       "auto_update": False},
    }
    return old, new


def test_unchanged_v1_parity():
    assert check_parity(*_pair()) == []


def test_rejects_entrypoint_and_activation_change():
    old, new = _pair()
    new["services"][0]["entrypoint"] = ["python", "wrong.py"]
    new["deployment"]["auto_update"] = True
    assert "PARITY:service.entrypoint" in check_parity(old, new)
    assert any(problem.startswith("POLICY:") for problem in check_parity(old, new))


def test_rejects_unapproved_rollback_change_and_secrets():
    old, new = _pair()
    new["deployment"]["rollback"] = False
    new["environment"]["required"] = ["UNDECLARED_SECRET"]
    issues = check_parity(old, new)
    assert "PARITY:deployment.rollback" in issues
    assert "PARITY:environment.required" in issues


def test_immutable_git_read_does_not_change_checkout(tmp_path):
    repo = tmp_path / "demo"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args],
                              text=True, capture_output=True, check=True).stdout.strip()
    git("init")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (repo / "uda.yaml").write_text("schema_version: 1\napplication: {name: sample}\n")
    git("add", "uda.yaml")
    git("commit", "-m", "fixture")
    git("branch", "feature/uda-manifest-v1")
    before = git("status", "--porcelain")
    doc, commit, digest = load_revision_file(repo, "feature/uda-manifest-v1", "uda.yaml")
    assert doc["schema_version"] == 1
    assert len(commit) == 40 and len(digest) == 64
    assert git("status", "--porcelain") == before



def _static_pair():
    old, new = _pair()
    old["runtime"] = {"type": "static", "working_dir": "."}
    old["service"] = {"type": "static", "port": 5094, "health_path": "/"}
    new.pop("services")
    new["static"] = {"output_dir": ".", "publication": "atomic-symlink"}
    new["deployment"]["strategy"] = "static"
    return old, new


def test_safe_allowlisted_staging_is_explicitly_supported():
    old, new = _static_pair()
    new["static"]["output_dir"] = "build/uda-public"
    new["builds"] = [{
        "name": "stage-public", "toolchain": "static",
        "commands": [["python3", "tools/uda_stage_static.py"]],
        "output_dir": "build/uda-public",
        "artifact": {"path": "build/uda-public", "kind": "static"},
    }]
    assert check_parity(old, new) == []


def test_arbitrary_static_output_change_is_rejected():
    old, new = _static_pair()
    new["static"]["output_dir"] = "build/anything"
    assert "PARITY:static.output_dir" in check_parity(old, new)


def test_staging_requires_exact_reviewed_command():
    old, new = _static_pair()
    new["static"]["output_dir"] = "build/uda-public"
    new["builds"] = [{
        "toolchain": "static",
        "commands": [["bash", "-c", "cp -r . build/uda-public"]],
        "output_dir": "build/uda-public",
        "artifact": {"path": "build/uda-public", "kind": "static"},
    }]
    assert "PARITY:static.output_dir" in check_parity(old, new)


def test_static_node_install_can_be_hardened_to_npm_ci():
    old, new = _static_pair()
    old["runtime"]["working_dir"] = "dist"
    old["build"] = {"commands": [
        ["npm", "install", "--no-package-lock"],
        ["npm", "run", "build"],
    ]}
    new["static"]["output_dir"] = "dist"
    new["builds"] = [{
        "toolchain": "node", "working_dir": ".",
        "commands": [["npm", "ci"], ["npm", "run", "build"]],
    }]
    assert check_parity(old, new) == []


def test_static_node_npm_ci_exception_does_not_allow_other_build_changes():
    old, new = _static_pair()
    old["runtime"]["working_dir"] = "dist"
    old["build"] = {"commands": [
        ["npm", "install", "--package-lock=false"],
        ["npm", "run", "build", "--", "--base=/apps/sample/"],
    ]}
    new["static"]["output_dir"] = "dist"
    new["builds"] = [{
        "toolchain": "node", "working_dir": ".",
        "commands": [["npm", "ci"], ["npm", "run", "build", "--", "--base=/wrong/"]],
    }]
    assert "PARITY:build.commands" in check_parity(old, new)
