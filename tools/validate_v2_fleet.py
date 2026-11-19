#!/usr/bin/env python3
"""Offline UDA V2 fleet validation: no network, build or host mutations."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import yaml
from jsonschema import Draft202012Validator

REPOS = (
    "general-search", "Notes", "XmasList", "flask_Motorbike-Cost-Tracker1",
    "mermaid-display-app", "mermaid_dashboard", "internet_pricing", "whisperdesk",
    "PackBridge", "querybridge", "wallpaper", "CatManager", "Allocraft", "GiftVault",
    "should-cost-intelligence-next", "AutoKeeper", "roundabout_designer", "CueCraft",
    "DAXBridge", "flowchain_studio",
)
BASE_REF = "feature/uda-manifest-v1"
V2_REF = "feature/uda-manifest-v2-review"

def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], text=True,
                            capture_output=True, timeout=25, check=False)
    if result.returncode:
        raise ValueError(f"git {args[0]} failed: {result.stderr.strip()[:160]}")
    return result.stdout

def load_revision_file(repo: Path, ref: str, path: str):
    commit = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    content = git(repo, "show", f"{commit}:{path}")
    if len(content.encode()) > 128 * 1024:
        raise ValueError(f"{path} is oversized")
    document = yaml.safe_load(content)
    if not isinstance(document, dict):
        raise ValueError(f"{path} is not a YAML mapping")
    return document, commit, sha256(content.encode()).hexdigest()

def check_parity(v1: dict, v2: dict) -> list[str]:
    problems = []
    def same(a, b, label):
        if a != b:
            problems.append(f"PARITY:{label}")
    same(v1["application"]["name"], v2["application"]["name"], "application.name")
    same(v1.get("source", {}).get("branch", "main"),
         v2.get("source", {}).get("branch", "main"), "source.branch")
    p1, p2 = v1.get("proxy", {}), v2.get("proxy", {})
    same(p1.get("enabled", False), p2.get("enabled", False), "proxy.enabled")
    if p1.get("enabled"):
        same(p1.get("path"), p2.get("canonical_path"), "proxy.path")
        same(p1.get("authentication"), p2.get("authentication"), "proxy.authentication")
    d1, d2 = v1.get("deployment", {}), v2.get("deployment", {})
    for key in ("rollback", "github_reporting"):
        same(d1.get(key), d2.get(key), f"deployment.{key}")
    if d2.get("approval") != "explicit" or d2.get("auto_update") is not False:
        problems.append("POLICY:V2 must require approval and disable auto-update")
    if v1["runtime"]["type"] == "static":
        same("static", d2.get("strategy"), "deployment.strategy")
        old_output = v1["runtime"].get("working_dir", ".")
        new_output = v2.get("static", {}).get("output_dir")
        if old_output != new_output:
            builds = v2.get("builds", [])
            reviewed_static_staging = (
                old_output == "." and new_output == "build/uda-public"
                and len(builds) == 1
                and builds[0].get("toolchain") == "static"
                and builds[0].get("commands") == [["python3", "tools/uda_stage_static.py"]]
                and builds[0].get("output_dir") == new_output
                and builds[0].get("artifact", {}).get("path") == new_output
                and builds[0].get("artifact", {}).get("kind") == "static"
            )
            if not reviewed_static_staging:
                problems.append("PARITY:static.output_dir")
            else:
                # Staging changes publication behaviour intentionally: the
                # separate artifact audit/build acceptance remains mandatory.
                pass
        if v2.get("services"):
            problems.append("PARITY:static has unexpected service")
    else:
        same("systemd", d2.get("strategy"), "deployment.strategy")
        services = v2.get("services", [])
        if len(services) != 1:
            problems.append("PARITY:V1 single service must remain single")
        else:
            s = services[0]
            same(v1["service"].get("entrypoint"), s.get("entrypoint"), "service.entrypoint")
            same(v1["service"].get("port"), s.get("port"), "service.port")
            same(v1["service"].get("health_path"), s.get("health", {}).get("path"), "service.health_path")
            same(v1["runtime"]["type"], s.get("runtime"), "service.runtime")
            same(v1["runtime"].get("working_dir", "."), s.get("working_dir", "."), "service.working_dir")
    old_commands = v1.get("build", {}).get("commands", [])
    new_commands = [cmd for b in v2.get("builds", []) for cmd in b.get("commands", [])]
    allowed_staging = (
        v1["runtime"]["type"] == "static"
        and v1["runtime"].get("working_dir", ".") == "."
        and v2.get("static", {}).get("output_dir") == "build/uda-public"
        and len(v2.get("builds", [])) == 1
        and v2["builds"][0].get("toolchain") == "static"
        and v2["builds"][0].get("output_dir") == "build/uda-public"
        and v2["builds"][0].get("artifact", {}).get("path") == "build/uda-public"
        and v2["builds"][0].get("artifact", {}).get("kind") == "static"
        and new_commands == old_commands + [["python3", "tools/uda_stage_static.py"]]
    )
    if not allowed_staging:
        same(old_commands, new_commands, "build.commands")
    same(set(v1.get("environment", {}).get("required", [])),
         set(v2.get("environment", {}).get("required", [])), "environment.required")
    return problems

def check_source(repo: Path, commit: str, v1: dict, v2: dict) -> list[str]:
    issues = []
    paths = set(git(repo, "ls-tree", "-r", "--name-only", commit).splitlines())
    def exists(path):
        return path in paths or any(p.startswith(path.rstrip("/") + "/") for p in paths)
    for build in v2.get("builds", []):
        wd = build.get("working_dir", ".")
        if wd != "." and not exists(wd):
            issues.append(f"SOURCE:missing build directory {wd}")
        for argv in build.get("commands", []):
            if "-r" in argv:
                i = argv.index("-r")
                if i+1 < len(argv):
                    path = argv[i+1] if wd == "." else f"{wd}/{argv[i+1]}"
                    if not exists(path):
                        issues.append(f"SOURCE:missing requirements {path}")
            if argv and argv[0] in ("python", "python3") and len(argv) > 1 and argv[1].endswith(".py"):
                script = argv[1] if wd == "." else f"{wd}/{argv[1]}"
                if not exists(script):
                    issues.append(f"SOURCE:missing build script {script}")
            if argv and argv[0] == "npm":
                package = "package.json" if wd == "." else f"{wd}/package.json"
                if not exists(package):
                    issues.append("SOURCE:npm command without package.json")
                locks = ("package-lock.json", "npm-shrinkwrap.json")
                if not any(exists(lock if wd == "." else f"{wd}/{lock}") for lock in locks):
                    issues.append("REVIEW:Node build lacks a pinned npm lockfile")
    for service in v2.get("services", []):
        wd = service.get("working_dir", ".")
        for token in service["entrypoint"][1:]:
            if token.endswith(".py") and not token.startswith("-"):
                path = token if wd == "." else f"{wd}/{token}"
                if not exists(path):
                    issues.append(f"SOURCE:missing Python entrypoint {path}")
    if v1["runtime"]["type"] == "static":
        output = v2["static"]["output_dir"]
        if output != "." and not exists(output):
            issues.append("REVIEW:generated static artifact requires isolated build")
        if output == ".":
            issues.append("REVIEW:static root publication requires artifact audit")
    return sorted(set(issues))

def evaluate(repo: Path, schema: dict, semantic_validate) -> dict:
    result = {"repository": f"zageabb/{repo.name}", "status": "FAIL",
              "errors": [], "warnings": []}
    try:
        old, old_rev, old_hash = load_revision_file(repo, BASE_REF, "uda.yaml")
        new, new_rev, new_hash = load_revision_file(repo, V2_REF, "uda.v2.yaml")
        result.update(v1_commit=old_rev, v2_commit=new_rev,
                      v1_sha256=old_hash, v2_sha256=new_hash)
        result["errors"].extend(check_parity(old, new))
        for issue in Draft202012Validator(schema).iter_errors(new):
            result["errors"].append(f"SCHEMA:{issue.json_path}:{issue.message}")
        if not any(e.startswith("SCHEMA:") for e in result["errors"]):
            try:
                semantic_validate(new)
            except ValueError as exc:
                result["errors"].append(f"SEMANTIC:{exc}")
        result["warnings"].extend(check_source(repo, new_rev, old, new))
        if new.get("source", {}).get("repository", "").casefold() != result["repository"].casefold():
            result["errors"].append("SOURCE:repository identity mismatch")
        result["status"] = ("FAIL" if result["errors"] else
                            "REVIEW" if result["warnings"] else "PASS")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, yaml.YAMLError) as exc:
        result["errors"].append(f"INSPECTION:{type(exc).__name__}: {str(exc)[:200]}")
    return result

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repos-root", type=Path, required=True,
                        help="Existing local Git repositories; no network fetching")
    parser.add_argument("--uda-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", choices=REPOS, action="append")
    options = parser.parse_args(argv)
    sys.path.insert(0, str(options.uda_root))
    from uda_manifest_v2_validate import validate
    schema = json.loads((options.uda_root / "schemas/uda-manifest-v2.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    results = [evaluate(options.repos_root / name, schema, validate)
               for name in (options.only or REPOS)]
    counts = {key: sum(r["status"] == key for r in results)
              for key in ("PASS", "REVIEW", "FAIL")}
    report = {"run_utc": datetime.now(timezone.utc).isoformat(),
              "mode": "read-only-local-git-objects",
              "manifest_commands_executed": False, "deployment_allowed": False,
              "refs": {"v1": BASE_REF, "v2": V2_REF},
              "counts": counts, "results": results,
              "scope_note": "Not runtime/build acceptance or production authorization."}
    options.out.parent.mkdir(parents=True, exist_ok=True)
    options.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(counts))
    return 2 if counts["FAIL"] else (1 if counts["REVIEW"] else 0)

if __name__ == "__main__":
    raise SystemExit(main())
