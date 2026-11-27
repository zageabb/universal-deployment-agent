"""Regression tests for commit-bound final fleet acceptance aggregation."""
import pytest

from tools.combine_v2_fleet_acceptance import combine


COMMIT = "a" * 40


def _fleet(status="REVIEW"):
    return {"results": [{
        "repository": "zageabb/DAXBridge", "status": status,
        "v2_commit": COMMIT,
    }]}


def _evidence(status="PASS", commit=COMMIT):
    return {
        "evidence_kind": "node-static-artifact-audit-v1",
        "production_modified": False,
        "results": [{
            "repository": "DAXBridge", "status": status,
            "source_commit": commit, "activation_allowed": False,
        }],
    }


def test_matching_pass_evidence_closes_review():
    report = combine(_fleet(), [_evidence()])
    assert report["counts"] == {"PASS": 1, "REVIEW": 0, "FAIL": 0}
    assert report["acceptance_complete"] is True
    assert report["deployment_allowed"] is False


def test_commit_mismatch_remains_review():
    report = combine(_fleet(), [_evidence(commit="b" * 40)])
    assert report["counts"]["REVIEW"] == 1
    assert report["results"][0]["reasons"] == ["ARTIFACT_COMMIT_MISMATCH"]


def test_artifact_failure_fails_combined_result():
    report = combine(_fleet(), [_evidence(status="FAIL")])
    assert report["counts"]["FAIL"] == 1


def test_missing_artifact_remains_review():
    report = combine(_fleet(), [])
    assert report["counts"]["REVIEW"] == 1
    assert report["acceptance_complete"] is False


def test_artifact_repository_still_requires_evidence_if_manifest_passes():
    report = combine(_fleet(status="PASS"), [])
    assert report["counts"]["REVIEW"] == 1


def test_rejects_activation_authority():
    evidence = _evidence()
    evidence["results"][0]["activation_allowed"] = True
    with pytest.raises(ValueError, match="permits activation"):
        combine(_fleet(), [evidence])


def test_rejects_duplicate_evidence():
    with pytest.raises(ValueError, match="duplicate"):
        combine(_fleet(), [_evidence(), _evidence()])
