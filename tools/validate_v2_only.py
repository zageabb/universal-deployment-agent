#!/usr/bin/env python3
"""Read-only independent inspection of V2-only manifests; no V1 parity baseline.

This tool never runs manifest-specified commands, writes to an app checkout,
fetches GitHub content, or touches a production service.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator
import yaml

from tools.validate_v2_fleet import git, load_revision_file

REPOS = (
    "tender_designer", "lucky-lab-slot-statistics", "Bank_of_mum",
    "context-studio", "research-core", "SideCar", "NetworkBridge",
    "Sheetbridge", "LedgerOne", "bottle_factory_game",
    "should-cost-intelligence",
)
REF = "feature/uda-v2-review"

# Explicit unresolved source/host gates. These cannot be cleared by a
# successful schema parse or by source-only checks.
REVIEW_GATES = {
    "tender_designer": ("MAILBOX_SERVICE_OWNERSHIP", "PERSISTENT_SQLITE_BACKUP"),
    "lucky-lab-slot-statistics": ("STARTUP_MIGRATION_AND_SEED", "SQLITE_BIND_BACKUP"),
    "Bank_of_mum": ("STARTUP_SCHEMA_AND_LEDGER_MUTATIONS", "PROXY_ROUTE_REVIEW"),
    "context-studio": ("STARTUP_DB_MIGRATIONS", "VINEXT_UBUNTU_RUNTIME"),
    "research-core": ("ISOLATED_WHEEL_TEST", "CONSUMER_PIN_REVIEW"),
    "SideCar": ("LIVE_VOLUME_ID_AND_BACKUP", "WEBSOCKET_AND_SECRET_TRUST"),
    "NetworkBridge": ("STARTUP_SQLITE_SCHEMA_WRITES", "ROUTER_DISCOVERY_PERMISSIONS"),
    "Sheetbridge": ("UDA_ASSERTION_TRUST", "OPTIONAL_FORMS_SQLITE_STORAGE"),
    "LedgerOne": ("ACCOUNTING_BOOTSTRAP_AND_MIGRATIONS", "PRODUCTION_WSGI_REVIEW"),
    "bottle_factory_game": ("NPM_LOCKFILE_MISSING", "LEGACY_UNDERSCORE_ROUTE"),
    "should-cost-intelligence": ("STARTUP_SCHEMA_WRITES", "PRICING_EVIDENCE_BACKUP"),
}


def inspect(repo: Path, schema: dict, semantic_validate) -> dict:
    result = {"repository": f"zageabb/{repo.name}", "status": "FAIL",
              "errors": [], "warnings": []}
    try:
        doc, rev, digest = load_revision_file(repo, REF, "uda.v2.yaml")
        result.update(v2_commit=rev, v2_sha256=digest)
        issues = sorted(Draft202012Validator(schema).iter_errors(doc),
                        key=lambda item: (str(item.json_path), item.message))
        result["errors"].extend(f"SCHEMA:{item.json_path}:{item.message}" for item in issues)
        if not issues:
            try:
                semantic_validate(doc)
            except ValueError as exc:
                result["errors"].append(f"SEMANTIC:{exc}")
        if doc.get("source", {}).get("repository", "").casefold() != result["repository"].casefold():
            result["errors"].append("SOURCE:repository identity mismatch")
        if doc.get("deployment", {}).get("approval") != "explicit" or doc.get("deployment", {}).get("auto_update") is not False:
            result["errors"].append("POLICY:explicit approval and auto_update=false required")
        if doc.get("deployment", {}).get("rollback") is not False:
            result["warnings"].append("REVIEW:unverified rollback must remain disabled")
        paths = set(git(repo, "ls-tree", "-r", "--name-only", rev).splitlines())
        def exists(p):
            return p in paths or any(f.startswith(p.rstrip("/") + "/") for f in paths)
        for build in doc.get("builds", []):
            wd = build.get("working_dir", ".")
            if wd != "." and not exists(wd):
                result["errors"].append(f"SOURCE:missing build working_dir {wd}")
            for cmd in build.get("commands", []):
                if "-r" in cmd:
                    index = cmd.index("-r")
                    if index + 1 < len(cmd):
                        req = cmd[index + 1]
                        path = req if wd == "." else f"{wd}/{req}"
                        if not exists(path):
                            result["errors"].append(f"SOURCE:missing requirements {path}")
                if cmd and cmd[0] == "npm":
                    lockdir = "" if wd == "." else wd + "/"
                    if not exists(lockdir + "package.json"):
                        result["errors"].append(f"SOURCE:missing package.json in {wd}")
                    if not (exists(lockdir + "package-lock.json") or exists(lockdir + "npm-shrinkwrap.json")):
                        result["warnings"].append(f"REVIEW:missing npm lockfile in {wd}")
        for svc in doc.get("services", []):
            wd = svc.get("working_dir", ".")
            for token in svc.get("entrypoint", []):
                if token.endswith((".py", ".sh")) and not token.startswith("-"):
                    path = token if wd == "." else wd + "/" + token
                    if not exists(path):
                        result["errors"].append(f"SOURCE:missing entrypoint {path}")
        for ctr in doc.get("containers", []):
            if "build" in ctr:
                bd = ctr["build"]
                if not exists(bd["dockerfile"]):
                    result["errors"].append(f"SOURCE:missing Dockerfile {bd['dockerfile']}")
        result["warnings"].extend(f"REVIEW_GATE:{code}" for code in REVIEW_GATES.get(repo.name, ()))
        # No host/persistence proof exists in a Git object. Review is required.
        result["warnings"].append("REVIEW:effective host, persistence, security, and runtime acceptance pending")
        if doc.get("databases") or doc.get("containers"):
            result["warnings"].append("REVIEW:data backup and lifecycle approval pending")
        result["errors"] = sorted(set(result["errors"]))
        result["warnings"] = sorted(set(result["warnings"]))
        result["status"] = ("FAIL" if result["errors"] else "REVIEW")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, yaml.YAMLError) as exc:
        result["errors"].append(f"INSPECTION:{type(exc).__name__}:{str(exc)[:200]}")
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repos-root", required=True, type=Path)
    p.add_argument("--uda-root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--only", choices=REPOS, action="append")
    opts = p.parse_args(argv)
    sys.path.insert(0, str(opts.uda_root))
    from uda_manifest_v2_validate import validate
    schema = json.loads((opts.uda_root / "schemas/uda-manifest-v2.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    results = [inspect(opts.repos_root / name, schema, validate) for name in opts.only or REPOS]
    counts = {s: sum(r["status"] == s for r in results) for s in ("PASS", "REVIEW", "FAIL")}
    report = {"run_utc": datetime.now(timezone.utc).isoformat(),
              "mode": "read-only-v2-only-git-objects", "manifest_commands_executed": False,
              "production_modified": False, "deployment_allowed": False,
              "counts": counts, "results": results}
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    opts.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts))
    return 2 if counts["FAIL"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
