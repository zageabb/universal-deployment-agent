"""Read-only release inventory tests; isolated fixtures, no production paths."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.v2_release_evidence import RUNTIME_FILES, collect, main


def setup_private_runtime(tmp_path):
    runtime = tmp_path / "installed"
    runtime.mkdir(mode=0o700)
    for relative in RUNTIME_FILES:
        path = runtime / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("fixture:" + relative).encode())
        path.chmod(0o644)
    config = tmp_path / "private" / "config.json"
    config.parent.mkdir(mode=0o700)
    config.write_text('{"dashboard_token":"DO-NOT-LEAK-THIS-SECRET"}')
    config.chmod(0o600)
    return runtime, config


def test_complete_uses_allowlisted_files_and_never_reports_config_contents(tmp_path):
    runtime, config = setup_private_runtime(tmp_path)
    result = collect(runtime=runtime, config=config)
    assert result["runtime_complete"]
    assert result["issues_for_operator_review"] == []
    assert result["protected_config"]["mode_octal"] == "0600"
    assert result["files"][0]["sha256"] == hashlib.sha256(
        ("fixture:" + RUNTIME_FILES[0]).encode()).hexdigest()
    assert "DO-NOT-LEAK" not in json.dumps(result)
    assert str(tmp_path) not in json.dumps(result)
    assert result["backup_verified"] is False
    assert result["rollback_verified"] is False
    assert result["production_upgrade_authorized"] is False


def test_missing_module_is_reported_without_source_fallback(tmp_path):
    runtime, config = setup_private_runtime(tmp_path)
    (runtime / "approval_centre.py").unlink()
    result = collect(runtime=runtime, config=config)
    assert not result["runtime_complete"]
    assert "runtime_files_missing_or_unreadable" in result["issues_for_operator_review"]
    assert next(x for x in result["files"] if x["file"] ==
                "approval_centre.py")["status"] == "unavailable"


def test_symlinked_module_is_refused(tmp_path):
    runtime, config = setup_private_runtime(tmp_path)
    target = runtime / "approval_centre.py"
    target.unlink()
    target.symlink_to(config)
    result = collect(runtime=runtime, config=config)
    assert not result["runtime_complete"]
    item = next(x for x in result["files"] if x["file"] ==
                "approval_centre.py")
    assert item["status"] == "symlink_refused"
    assert "sha256" not in item


def test_broad_config_permissions_and_writable_runtime_are_flagged(tmp_path):
    runtime, config = setup_private_runtime(tmp_path)
    runtime.chmod(0o775)
    config.chmod(0o644)
    result = collect(runtime=runtime, config=config)
    assert "runtime_directory_writable_by_others" in result["issues_for_operator_review"]
    assert "config_permissions_too_broad" in result["issues_for_operator_review"]
    assert result["protected_config"]["mode_octal"] == "0644"


def test_config_symlink_is_never_opened(tmp_path):
    runtime, config = setup_private_runtime(tmp_path)
    old = config.with_suffix(".real")
    config.rename(old)
    config.symlink_to(old)
    result = collect(runtime=runtime, config=config)
    assert result["protected_config"]["status"] == "not_regular_or_symlink"
    assert "config_metadata_unavailable" in result["issues_for_operator_review"]


def test_cli_never_prints_or_reads_config_content(tmp_path, monkeypatch, capsys):
    runtime, config = setup_private_runtime(tmp_path)
    monkeypatch.setattr("sys.argv", ["read-only-evidence",
                                    "--runtime", str(runtime),
                                    "--config", str(config)])
    assert main() == 0
    output = capsys.readouterr().out
    assert json.loads(output)["runtime_complete"] is True
    assert "DO-NOT-LEAK-THIS-SECRET" not in output
