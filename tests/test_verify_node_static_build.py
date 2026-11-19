"""Disposable fixture tests for the independent post-build artifact verifier."""
from pathlib import Path

from tools.verify_node_static_build import audit_dist


def _fixture(tmp_path: Path, lock=True):
    root = tmp_path / "DAXBridge"
    (root / "dist/assets").mkdir(parents=True)
    if lock:
        (root / "package-lock.json").write_text('{"lockfileVersion":3}')
    (root / "dist/index.html").write_text(
        '<script type="module" src="/apps/daxbridge/assets/main.js"></script>')
    (root / "dist/assets/main.js").write_text('console.log("ready")')
    return root


def test_safe_pinned_artifact_inventory_passes(tmp_path):
    report = audit_dist(_fixture(tmp_path), "DAXBridge")
    assert report["status"] == "PASS"
    assert report["activation_allowed"] is False
    assert len(report["files"]) == 2


def test_missing_lockfile_requires_review(tmp_path):
    report = audit_dist(_fixture(tmp_path, lock=False), "DAXBridge")
    assert report["status"] == "REVIEW"
    assert "MISSING_LOCKFILE" in report["warnings"][0]


def test_wrong_asset_base_fails(tmp_path):
    root = _fixture(tmp_path)
    (root / "dist/index.html").write_text(
        '<script src="/apps/not-daxbridge/assets/main.js"></script>')
    report = audit_dist(root, "DAXBridge")
    assert report["status"] == "FAIL"
    assert any(e.startswith("BAD_BASE_PATH:") for e in report["errors"])


def test_symlink_asset_rejected(tmp_path):
    root = _fixture(tmp_path)
    (root / "dist/assets/main.js").unlink()
    (root / "dist/assets/main.js").symlink_to(root / "dist/index.html")
    report = audit_dist(root, "DAXBridge")
    assert report["status"] == "FAIL"
    assert any(e.startswith("SYMLINK:") for e in report["errors"])


def test_missing_generated_output_requires_review(tmp_path):
    root = tmp_path / "flowchain_studio"
    root.mkdir()
    result = audit_dist(root, "flowchain_studio")
    assert result["status"] == "REVIEW"
    assert result["activation_allowed"] is False


def test_source_map_rejected(tmp_path):
    root = _fixture(tmp_path)
    (root / "dist/assets/main.js.map").write_text("{}")
    report = audit_dist(root, "DAXBridge")
    assert report["status"] == "FAIL"
    assert any("FORBIDDEN_FILE_TYPE" in x for x in report["errors"])
