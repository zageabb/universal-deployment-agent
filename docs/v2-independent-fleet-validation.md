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

## Follow-on static artifact acceptance (six REVIEW results, 19 November 2026)

The independent fleet evidence reports 14 PASS, 6 REVIEW, 0 FAIL and four passing
runner tests. The six REVIEW entries are expected: Wallpaper Studio, Roundabout
Designer and CueCraft use repository-root static publication; Should-Cost Next,
DAXBridge and Flowchain Studio require generated dist builds.

Use the extra **read-only** Git-object audit (no scripts are executed):

    python tools/validate_static_artifacts.py \
      --repos-root /path/to/disposable/repositories \
      --out /path/to/evidence/uda-v2-static-artifacts.json
    python -m pytest -q tests/test_validate_static_artifacts.py

The audit resolves immutable commits, enumerates tracked output paths and flags
configuration/source files, hidden/sensitive directories and symlinks. A repository-root
publication remains REVIEW **even when only apparently safe tracked files exist**:
untracked files and the Git directory must not be exposed by a live web-server document
root. For generated `dist/`, a Git-tree review does not prove a successful build.

Required separate acceptance:
1. Root-published apps: in a disposable checkout build a *new* allowlisted
   publication directory containing only explicitly approved web assets; inspect
   relative URLs, file list, symlink policy, headers and deny access to
   .git/.env/source/config/backup paths. Compare the intended runtime document
   root to the isolated staging directory before approving a manifest change.
2. Generated apps: pin commits, use an isolated unprivileged build sandbox with
   no production environment/credentials, and run the repository's reviewed
   install/build commands (not arbitrary argv loaded from a manifest). Confirm
   build exit 0, dist/index.html, asset hashes and that dist contains no source
   maps, credentials, backend data, symlinks or unexpected files. Record Node,
   npm, lockfile version, command, hashes, logs and dependency review.
3. Execute application tests only within that sandbox, not as evidence of
   production runtime. Verify routed /apps/<slug>/ assets and UDA login/SSO
   separately under approved controlled acceptance.
4. Attach explicit per-application evidence and owner sign-off before changing
   REVIEW status. Never adjust status based solely on the audit script output.

**Important:** this audit is intentionally conservative: its output will not
turn REVIEW to PASS automatically. It only identifies evidence and concrete
risks, while the existing fleet JSON report remains the manifest-gate baseline.
