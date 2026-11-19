#!/usr/bin/env python3
"""Read-only verification of prebuilt Node V2 static bundles. Never executes npm."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import stat
import subprocess

NAMES = ("should-cost-intelligence-next", "DAXBridge", "flowchain_studio")
EXPECTED = {
    "should-cost-intelligence-next": ("should-cost-intelligence-next", ("./assets/", "/apps/should-cost-intelligence-next/")),
    "DAXBridge": ("daxbridge", ("/apps/daxbridge/",)),
    "flowchain_studio": ("flowchain-studio", ("/apps/flowchain-studio/",)),
}
ALLOWED = {".html", ".css", ".js", ".mjs", ".png", ".jpg", ".jpeg", ".gif",
           ".svg", ".ico", ".webp", ".woff", ".woff2", ".ttf", ".webmanifest",
           ".wasm", ".txt", ".json", ".mp4", ".webm"}
DISALLOWED = {".map", ".pem", ".key", ".p12", ".pfx", ".env", ".sqlite", ".db",
              ".yaml", ".yml", ".py", ".ts", ".tsx", ".sh", ".md"}
SENSITIVE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}")

def audit_dist(root: Path, name: str) -> dict:
    if name not in EXPECTED:
        raise ValueError("Unsupported repository name")
    app, prefix_options = EXPECTED[name]
    problems, warnings, entries = [], [], []
    if not (root / "package-lock.json").is_file() and not (root / "npm-shrinkwrap.json").is_file():
        warnings.append("MISSING_LOCKFILE: reviewed reproducible install is required")
    dist = root / "dist"
    if not dist.is_dir() or dist.is_symlink():
        warnings.append("MISSING_BUILD: no completed dist artifact")
        return {"repository": name, "status": "REVIEW", "errors": problems,
                "warnings": warnings, "files": entries, "activation_allowed": False}
    if not (dist / "index.html").is_file() or (dist / "index.html").is_symlink():
        problems.append("MISSING_INDEX: built index.html required")
    for path in sorted(dist.rglob("*")):
        rel = path.relative_to(dist).as_posix()
        if path.is_symlink():
            problems.append(f"SYMLINK:{rel}")
            continue
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            problems.append(f"NONREGULAR:{rel}")
            continue
        suffix = path.suffix.lower()
        if any(part.startswith(".") for part in path.relative_to(dist).parts):
            problems.append(f"HIDDEN_FILE:{rel}")
        if suffix in DISALLOWED or suffix not in ALLOWED:
            problems.append(f"FORBIDDEN_FILE_TYPE:{rel}")
        if path.stat().st_size > 40 * 1024 * 1024:
            warnings.append(f"LARGE_ARTIFACT:{rel}")
        data = path.read_bytes()
        if SENSITIVE.search(data.decode("utf-8", errors="ignore")):
            problems.append(f"SENSITIVE_CONTENT:{rel}")
        entries.append({"path": rel, "sha256": sha256(data).hexdigest(), "bytes": len(data)})
    index = dist / "index.html"
    if index.is_file() and not index.is_symlink():
        html = index.read_text(encoding="utf-8", errors="replace")
        local_refs = re.findall(r"""(?:src|href)=["']([^"']+)["']""", html)
        assets = [r for r in local_refs if ("/assets/" in r or r.startswith("./assets/"))]
        if not assets:
            warnings.append("ASSET_REFERENCES: no bundled index asset references discovered")
        for asset in assets:
            if not any(asset.startswith(prefix) for prefix in prefix_options):
                problems.append(f"BAD_BASE_PATH:{asset[:160]}")
                continue
            if asset.startswith("./"):
                rel = asset[2:]
            else:
                rel = asset.split("/assets/", 1)[-1]
                rel = "assets/" + rel
            rel = rel.split("?", 1)[0].split("#", 1)[0]
            if ".." in Path(rel).parts or rel.startswith(("/", "\\")):
                problems.append(f"UNSAFE_ASSET_PATH:{rel[:160]}")
                continue
            if not (dist / rel).is_file():
                problems.append(f"MISSING_ASSET:{rel}")
    return {"repository": name, "application": app,
            "status": "FAIL" if problems else "REVIEW" if warnings else "PASS",
            "errors": sorted(set(problems)), "warnings": sorted(set(warnings)),
            "files": entries, "activation_allowed": False}

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repos-root", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--only", choices=NAMES, action="append")
    opts = p.parse_args(argv)
    results = [audit_dist(opts.repos_root / name, name) for name in opts.only or NAMES]
    totals = {s: sum(r["status"] == s for r in results) for s in ("PASS", "REVIEW", "FAIL")}
    evidence = {"run_utc": datetime.now(timezone.utc).isoformat(),
                "mode": "read-only-existing-artifact", "npm_executed": False,
                "production_modified": False, "counts": totals, "results": results,
                "scope_note": "PASS is artifact inspection only, not build provenance, runtime or deployment sign-off"}
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    opts.out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(totals))
    return 2 if totals["FAIL"] else 1 if totals["REVIEW"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
