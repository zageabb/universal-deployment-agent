#!/usr/bin/env python3
"""Read-only inspection of V2 static publication candidates from immutable Git refs.

Does not run npm, scripts, publish static sites, or access production state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import subprocess

import yaml

STATIC_REPOS = (
    "wallpaper", "roundabout_designer", "CueCraft", "should-cost-intelligence-next",
    "DAXBridge", "flowchain_studio",
)
REF = "feature/uda-manifest-v2-review"
BLOCKED_COMPONENTS = {
    ".git", ".github", ".env", ".venv", "venv", "node_modules",
    "__pycache__", ".pytest_cache", ".idea", ".vscode", "tests", "test",
    "docs", "backup", "backups", "secrets", "private", "data", "instance",
}
BLOCKED_SUFFIXES = {
    ".py", ".sh", ".md", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".pfx",
    ".log", ".map", ".lock", ".ts", ".tsx", ".jsx", ".json",
}
SAFE_WEB_SUFFIXES = {
    ".html", ".htm", ".css", ".js", ".mjs", ".svg", ".png",
    ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".woff", ".woff2",
    ".ttf", ".otf", ".webmanifest", ".txt", ".mp4", ".webm",
}


def git(repo: Path, *argv: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *argv], capture_output=True,
                       check=False, timeout=25)
    if p.returncode:
        raise ValueError(f"git {argv[0]} failed (exit {p.returncode})")
    return p.stdout.decode("utf-8", errors="strict")


def inspect_tree(repo: Path, ref: str = REF) -> dict:
    commit = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    manifest_bytes = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:uda.v2.yaml"],
        capture_output=True, timeout=25, check=False)
    if manifest_bytes.returncode or len(manifest_bytes.stdout) > 131072:
        raise ValueError("Missing or oversized V2 manifest")
    manifest = yaml.safe_load(manifest_bytes.stdout)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        raise ValueError("Expected V2 manifest")
    if manifest.get("deployment", {}).get("strategy") != "static":
        raise ValueError("Not a static deployment")
    output_dir = manifest.get("static", {}).get("output_dir")
    if not isinstance(output_dir, str) or not output_dir or output_dir.startswith("/") or ".." in PurePosixPath(output_dir).parts:
        raise ValueError("Unsafe static output directory")
    raw = git(repo, "ls-tree", "-rz", "--full-tree", commit)
    entries = []
    for item in raw.split("\0"):
        if not item:
            continue
        metadata, path = item.split("\t", 1)
        mode, kind, _ = metadata.split(" ", 2)
        entries.append((path, mode, kind))
    prefix = "" if output_dir == "." else output_dir.rstrip("/") + "/"
    included = [(p, m, k) for p, m, k in entries if p.startswith(prefix)]
    risks = []
    web_candidates = []
    for path, mode, kind in included:
        relative = path[len(prefix):]
        parts = PurePosixPath(relative).parts
        base = parts[-1].lower()
        suffix = PurePosixPath(base).suffix
        if kind != "blob" or mode not in ("100644", "100755"):
            risks.append({"path": relative, "reason": "nonregular-or-symlink"})
        elif any(p.lower() in BLOCKED_COMPONENTS or p.lower().startswith(".env") for p in parts):
            risks.append({"path": relative, "reason": "sensitive-or-nonpublic-directory"})
        elif base in ("dockerfile", "makefile", "package.json", "tsconfig.json", "vite.config.js", "vite.config.ts", "package-lock.json") or suffix in BLOCKED_SUFFIXES:
            risks.append({"path": relative, "reason": "source-config-or-build-file"})
        elif suffix not in SAFE_WEB_SUFFIXES:
            risks.append({"path": relative, "reason": "unrecognized-public-file-type"})
        else:
            web_candidates.append(relative)
    index_present = "index.html" in web_candidates
    # Root publication cannot be certified from a tracked tree: untracked files,
    # generated content, and .git may exist if a server exposes the checkout.
    reasons = []
    if output_dir == ".":
        reasons.append("root-publication-requires-allowlisted-staging-and-runtime-document-root-verification")
    else:
        reasons.append("isolated-build-required-before-generated-artifact-acceptance")
    if risks:
        reasons.append("tracked-files-would-be-unsafe-if-published-unfiltered")
    if not index_present:
        reasons.append("index-html-not-present-in-committed-output")
    return {
        "repository": f"zageabb/{repo.name}", "status": "REVIEW",
        "commit": commit,
        "manifest_sha256": sha256(manifest_bytes.stdout).hexdigest(),
        "output_dir": output_dir,
        "tracked_files_in_output_dir": len(included),
        "potentially_public_files": len(web_candidates),
        "potentially_unsafe_files": risks,
        "index_in_git": index_present,
        "reasons": reasons,
        "runtime_or_build_verified": False,
        "activation_allowed": False,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repos-root", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--only", choices=STATIC_REPOS, action="append")
    opts = p.parse_args(argv)
    results = []
    for name in opts.only or STATIC_REPOS:
        try:
            results.append(inspect_tree(opts.repos_root / name))
        except (ValueError, OSError, subprocess.SubprocessError, yaml.YAMLError) as exc:
            results.append({"repository": f"zageabb/{name}", "status": "FAIL", "errors": [f"{type(exc).__name__}:{str(exc)[:120]}"]})
    counts = {status: sum(r["status"] == status for r in results) for status in ("PASS", "REVIEW", "FAIL")}
    evidence = {"run_utc": datetime.now(timezone.utc).isoformat(), "read_only": True,
                "builds_executed": False, "production_modified": False,
                "counts": counts, "results": results}
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    opts.out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts))
    return 2 if counts["FAIL"] else (1 if counts["REVIEW"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
