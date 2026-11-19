# Independent UDA V2 fleet acceptance (20 V1 conversions)

Status: read-only manifest validation; no deployment approval.

The CLI is independent of GitHub Actions, ForgeBridge, MCP and production systemd/Caddy. It uses the official UDA V2 JSON Schema and semantic validator. It only reads immutable Git objects in existing local checkouts. It does NOT run build commands, installs, systemctl, Docker or migrations.

## Preparation

Use a disposable development workstation or isolated directory, NOT the production checkout. Have Python, Git, PyYAML and jsonschema installed in an isolated virtual environment.

Place all 20 repositories as direct subdirectories under one repos-root, using the exact names in tools/validate_v2_fleet.py. Both refs must be present in each local Git repository:

- feature/uda-manifest-v1: root uda.yaml
- feature/uda-manifest-v2-review: uda.v2.yaml

For an explicit disposable fetch into a NEW directory, use: bash tools/prepare_v2_fleet_workspace.sh /path/to/new-fleet-clones . This is a separate network-writing preparation step; the validator itself is offline. Check repository access before running it. GitHub Actions is not needed. For the GitHub repository Internet_pricing, name its local destination directory internet_pricing for compatibility with the fleet inventory. Never embed GitHub credentials in the report.

## Execute

From an isolated checkout of this UDA branch:

    python3 -m venv /tmp/uda-v2-fleet-venv
    /tmp/uda-v2-fleet-venv/bin/python -m pip install -r requirements.txt pytest
    /tmp/uda-v2-fleet-venv/bin/python tools/validate_v2_fleet.py --repos-root /path/to/clones --uda-root . --out /path/to/evidence/uda-v2-fleet.json
    /tmp/uda-v2-fleet-venv/bin/python -m pytest -q tests/test_validate_v2_fleet.py

Option --only Notes can be repeated to select a subset. The runner never checks out, fetches or updates refs. It resolves immutable commit SHAs and stores the source manifest SHA-256 digests.

Exit code 0 = all PASS; 1 = REVIEW without FAIL; 2 = at least one FAIL. Missing objects, malformed YAML and semantic/schema violations fail closed.

## Covered gates

1. YAML parse and Draft202012Validator shape validation.
2. Official UDA V2 semantic graph validation.
3. V1 parity: name, branch, proxy/authentication, build argv, service entrypoint, port, health, environment names and rollback declaration.
4. Explicit approval and disabled auto_update.
5. Static source checks of declared build paths, requirements files, npm package files and Python script entrypoints.
6. JSON report with per-repo result, pinned Git commits and manifest digests.

Source inspection does not prove application startup, installed dependencies, compiled assets, safe DB migrations, service ownership, production rollback or health. Static root publication and not-yet-built static artifacts require further manual REVIEW. Build/runtime tests must run separately in a disposable sandbox and must never execute untrusted YAML argv as part of this read-only validator.

V2 files remain named uda.v2.yaml, not uda.yaml. This avoids activating V2 accidentally. Each V2 PR targets its existing V1 feature branch. Neither the V1 nor V2 manifest PRs may be merged based solely on this acceptance report. UDA PR #26 retains a separate production-host approval gate.

Retain JSON evidence, runner commit, UDA schema/semantic validator commit, and independent build reports. Redact local path/username details before sharing. Never publish secret values or upload reports to GitHub without separate approval.
