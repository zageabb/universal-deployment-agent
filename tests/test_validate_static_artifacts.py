"""Regression tests for read-only static publication auditing."""
import subprocess
import yaml

from tools.validate_static_artifacts import inspect_tree


def repo(tmp_path, files, output_dir="."):
    path = tmp_path / "wallpaper"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Tester"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "tester@example.invalid"], check=True)
    for name, content in files.items():
        dest = path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
    manifest = {"schema_version": 2, "deployment": {"strategy": "static"},
                "static": {"output_dir": output_dir}}
    (path / "uda.v2.yaml").write_text(yaml.safe_dump(manifest))
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "Fixture"], check=True)
    subprocess.run(["git", "-C", str(path), "branch", "feature/uda-manifest-v2-review"], check=True)
    return path


def test_root_publication_is_never_implicitly_passed(tmp_path):
    result = inspect_tree(repo(tmp_path, {"index.html": "<h1>hello</h1>"}))
    assert result["status"] == "REVIEW"
    assert result["index_in_git"]
    assert "root-publication-requires-allowlisted-staging-and-runtime-document-root-verification" in result["reasons"]


def test_root_reports_sensitive_tracked_files(tmp_path):
    result = inspect_tree(repo(tmp_path, {"index.html": "ok", ".env": "secret", "app.py": "print(1)"}))
    reasons = {x["reason"] for x in result["potentially_unsafe_files"]}
    assert "sensitive-or-nonpublic-directory" in reasons
    assert "source-config-or-build-file" in reasons
    assert result["activation_allowed"] is False


def test_generated_dist_needs_build(tmp_path):
    result = inspect_tree(repo(tmp_path, {"package.json": "{}", "src/main.ts": "ok"}, "dist"))
    assert result["status"] == "REVIEW"
    assert result["tracked_files_in_output_dir"] == 0
    assert "isolated-build-required-before-generated-artifact-acceptance" in result["reasons"]


def test_symlink_is_not_cleared(tmp_path):
    import os
    path = repo(tmp_path, {"index.html": "ok"})
    os.symlink("index.html", path / "link.js")
    subprocess.run(["git", "-C", str(path), "add", "link.js"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "link"], check=True)
    subprocess.run(["git", "-C", str(path), "branch", "-f", "feature/uda-manifest-v2-review"], check=True)
    result = inspect_tree(path)
    assert any(x["reason"] == "nonregular-or-symlink" for x in result["potentially_unsafe_files"])
