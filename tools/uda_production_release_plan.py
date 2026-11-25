"""Read-only production transaction contract; no live mutation entry point.

Freeze exact old/new identities and original service states into a review
record. A digest detects drift, not malicious modification or authorization.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import socket
import os
import subprocess

from tools import uda_production_admission as admission
from tools.uda_controlled_activation import State, admission as isolated_admission
from tools.uda_runtime_integrity import ROOT


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def contract(report, baseline, revision, host, uid):
    admission.review_inventory(report)
    if baseline["status"] != "BASELINE_PASS" or baseline["actions"] != report["actions"]:
        raise ValueError("Baseline and inventory mismatch")
    states = {u: State(**s) for u, s in baseline["unit_states"].items()}
    admission.review_states(states)
    mutations = {}
    preserved = {}
    for name, entry in sorted(report["entries"].items()):
        old, new = entry["installed"], entry["candidate"]
        if entry["action"] in {"add", "replace"}:
            if not name.startswith("runtime/"):
                raise ValueError("Non-runtime mutation refused")
            mutations[name] = {"old": None if old["status"] == "missing" else old,
                               "new": new, "action": entry["action"]}
        else:
            preserved[name] = old
    if len(mutations) != 38 or len(preserved) != 24:
        raise ValueError("Unexpected transaction scope")
    body = {"version": 1, "revision": revision, "host": host, "uid": uid,
            "mutations": mutations, "preserved": preserved,
            "units": report["units"], "original_states": baseline["unit_states"],
            "venv": {"stable": "venv", "candidate": "venv-v2",
                     "retained": "venv-v1-retained"}}
    return {"contract": body, "sha256": digest(body),
            "status": "PLAN_ONLY", "production_upgrade_authorized": False}


def verify_unchanged(expected, current):
    for record in (expected, current):
        if record.get("status") != "PLAN_ONLY" or record.get("production_upgrade_authorized") is not False:
            raise ValueError("Unexpected contract status")
        if digest(record["contract"]) != record["sha256"]:
            raise ValueError("Contract digest mismatch")
    if expected != current:
        raise ValueError("Production baseline drift")


def isolation_review(plan, isolated, *, writers_quiescent, backup_verified):
    if digest(plan["contract"]) != plan["sha256"]:
        raise ValueError("Contract digest mismatch")
    original = {u: State(**s) for u, s in plan["contract"]["original_states"].items()}
    isolated_admission(original, isolated, writers_quiescent=writers_quiescent,
                       backup_verified=backup_verified)
    return {"status": "ISOLATION_REVIEW_PASS", "production_upgrade_authorized": False}


def inspect(stage, *, candidate_receipt=None):
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, text=True).strip():
        raise ValueError("Release checkout is not clean")
    first = admission.collect(stage, Path.home())
    baseline = admission.inspect(stage) if candidate_receipt is None else admission.inspect(stage, candidate_receipt=candidate_receipt)
    second = admission.collect(stage, Path.home())
    if first != second:
        raise ValueError("Inventory changed during admission")
    plan = contract(second, baseline, revision, socket.gethostname(), os.getuid())
    if candidate_receipt is not None:
        plan['contract']['venv']['receipt'] = candidate_receipt
        plan['sha256'] = digest(plan['contract'])
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--candidate-receipt", type=Path)
    args = parser.parse_args()
    try:
        receipt = json.loads(args.candidate_receipt.read_text())["receipt"] if args.candidate_receipt else None
        print(json.dumps(inspect(args.stage, candidate_receipt=receipt), indent=2, sort_keys=True))
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "REVIEW", "error": str(exc),
                          "production_upgrade_authorized": False}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
