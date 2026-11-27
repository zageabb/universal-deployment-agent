#!/usr/bin/env python3
"""Combine manifest validation with commit-bound static artifact evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


ARTIFACT_REPOS = {
    "wallpaper", "roundabout_designer", "CueCraft",
    "should-cost-intelligence-next", "DAXBridge", "flowchain_studio",
}
EVIDENCE_KINDS = {
    "static-staging-audit-v1", "node-static-artifact-audit-v1",
}


def _name(value: str) -> str:
    return value.rsplit("/", 1)[-1]


def load_report(path: Path) -> dict:
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError(f"oversized evidence: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("results"), list):
        raise ValueError(f"invalid evidence structure: {path.name}")
    return value


def combine(fleet: dict, artifact_reports: list[dict]) -> dict:
    artifacts: dict[str, dict] = {}
    for report in artifact_reports:
        if report.get("evidence_kind") not in EVIDENCE_KINDS:
            raise ValueError("unsupported artifact evidence kind")
        if report.get("production_modified") is not False:
            raise ValueError("artifact evidence must state production_modified=false")
        for result in report["results"]:
            name = _name(str(result.get("repository", "")))
            if name not in ARTIFACT_REPOS:
                raise ValueError(f"unexpected artifact repository: {name}")
            if name in artifacts:
                raise ValueError(f"duplicate artifact evidence: {name}")
            if result.get("activation_allowed") is not False:
                raise ValueError(f"artifact evidence permits activation: {name}")
            artifacts[name] = result

    combined = []
    for manifest in fleet["results"]:
        name = _name(str(manifest.get("repository", "")))
        manifest_status = manifest.get("status")
        final_status = manifest_status
        reasons = []
        artifact = artifacts.get(name)
        if manifest_status != "FAIL" and name in ARTIFACT_REPOS:
            if artifact is None:
                final_status = "REVIEW"
                reasons.append("ARTIFACT_EVIDENCE_MISSING")
            else:
                source_commit = artifact.get("source_commit")
                if source_commit != manifest.get("v2_commit"):
                    final_status = "REVIEW"
                    reasons.append("ARTIFACT_COMMIT_MISMATCH")
                elif artifact.get("status") == "PASS":
                    final_status = manifest_status
                    if manifest_status == "REVIEW":
                        final_status = "PASS"
                elif artifact.get("status") == "FAIL":
                    final_status = "FAIL"
                    reasons.append("ARTIFACT_AUDIT_FAILED")
                else:
                    final_status = "REVIEW"
                    reasons.append("ARTIFACT_AUDIT_REVIEW")
        combined.append({
            "repository": manifest.get("repository"),
            "v2_commit": manifest.get("v2_commit"),
            "manifest_status": manifest_status,
            "artifact_status": artifact.get("status") if artifact else None,
            "artifact_source_commit": artifact.get("source_commit") if artifact else None,
            "final_status": final_status,
            "reasons": reasons,
        })

    counts = {
        status: sum(item["final_status"] == status for item in combined)
        for status in ("PASS", "REVIEW", "FAIL")
    }
    return {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "combined-v2-fleet-acceptance-v1",
        "counts": counts,
        "acceptance_complete": not counts["REVIEW"] and not counts["FAIL"],
        "deployment_allowed": False,
        "activation_allowed": False,
        "results": combined,
        "scope_note": (
            "Combines manifest and commit-bound artifact evidence only; "
            "does not authorize merge, deployment or production activation."
        ),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fleet", required=True, type=Path)
    parser.add_argument("--artifact-evidence", required=True, type=Path, action="append")
    parser.add_argument("--out", required=True, type=Path)
    opts = parser.parse_args(argv)
    report = combine(
        load_report(opts.fleet),
        [load_report(path) for path in opts.artifact_evidence],
    )
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    opts.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["counts"]))
    return 2 if report["counts"]["FAIL"] else 1 if report["counts"]["REVIEW"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
