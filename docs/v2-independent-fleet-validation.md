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

## Review-only allowlisted static publication implementation (19 November 2026)

The following three **V2 feature branches** now include a fail-closed
`tools/uda_stage_static.py` and `tests/test_uda_stage_static.py`:

- `zageabb/wallpaper` — `index.html`, `styles.css`, `app.js`
- `zageabb/roundabout_designer` — `index.html`, `src/styles.css`
  and the 14 JavaScript modules explicitly loaded by `index.html`
- `zageabb/CueCraft` — standalone `index.html` only

Each V2 manifest now declares a reviewed static build command and
`build/uda-public` output with atomic-symlink publication; original
V1 `uda.yaml` files are untouched. The staging implementation:
- Refuses an existing output destination rather than deleting contents;
- Copies only fixed allowlisted regular files, preserving paths;
- Rejects symlink input/parents, missing/oversized files and missing HTML
  local asset references;
- Never places reports, secrets, build scripts or repository metadata into
  the public artifact;
- Emits file hashes and sizes to stdout, outside the public directory;
- Is **not** automatically executed by the read-only fleet/audit utilities.

For independent acceptance, operate on a fresh disposable clone pinned
to the V2 candidate commit, never the production checkout:

    python3 -m unittest discover -s tests -p test_uda_stage_static.py -v
    python3 tools/uda_stage_static.py

Capture the resulting file inventory/hashes and prove no file outside the
fixed allowlist is present in `build/uda-public`. Verify HTML/CSS asset
references and served `/apps/<slug>/` routes in a separate unprivileged
localhost test. Roundabout Designer's `deploy/serve.sh` now refuses to
serve unless this staged index exists. Confirm the effective UDA/Caddy
document-root before accepting any release.

The fleet parity validator recognises **only** this exact staging command
and output/artifact declaration as an intentional V1-to-V2 change;
arbitrary path or build changes remain errors. Staged artifacts are not
committed to Git; a source-tree-only audit remains REVIEW until independent
execution, publication boundary and runtime evidence are supplied.

**Status:** implementation committed; staging regression execution,
isolated artifact inspection and production-owner acceptance **not yet
verified**. No V2 activation or manifest merge is permitted.

## Generated Node static artifacts — next independent acceptance gate

The initial GitHub source review found `package-lock.json` on
Should-Cost Intelligence Next, but **no recognised npm lockfile** on
DAXBridge or Flowchain Studio. Do not treat `npm install` without a
reviewed lockfile as reproducible release-build evidence. Generate and review
the missing lockfiles on separate development branches before acceptance.

After an authorised operator has completed each **isolated, unprivileged**
Node build from a pinned Git commit, inspect its resulting `dist/` tree:

    python tools/verify_node_static_build.py \
      --repos-root /path/to/disposable-built-repositories \
      --out /path/to/evidence/uda-v2-node-artifacts.json
    python -m pytest -q tests/test_verify_node_static_build.py

The tool never invokes npm or executes bundle contents. It records file
SHA-256 digests and checks for missing `index.html`, missing assets, wrong
`/apps/<slug>/` base paths, symlinks, forbidden file types/source maps,
private-key/AWS-key signatures and missing lockfiles. A PASS is restricted
to **static artifact inspection** and must not be called runtime health,
build-provenance or production acceptance.

Required independent build procedure (outside the UDA production tree):
1. Pin the target V2 candidate commit and preserve source cleanliness.
2. Verify the reviewed Node/npm versions and npm lockfile. Refuse unpinned
   dependencies; review license/security concerns separately.
3. In a disposable unprivileged sandbox with no production secrets/DB/ports,
   use the reviewed repository build commands; record their exact command,
   exit status and stderr/stdout without secret values.
4. Verify the expected `dist/` tree using the read-only inspector above;
   exercise the application's test suite separately.
5. Check UDA-authenticated subpath routing and live document-root alignment
   with authorised Desktop read-only inspection before any release decision.

No builds were performed when this tooling was authored. That statement is
historical; the final acceptance procedure below records the later independent
execution without changing the conservative source-only classifications.

## Final commit-bound acceptance aggregation

The source-only fleet validator intentionally continues to report generated
artifacts as REVIEW. After every required isolated build/staging run has a
separate PASS report, combine the evidence without editing either source report:

    python tools/combine_v2_fleet_acceptance.py \
      --fleet /path/to/evidence/uda-v2-fleet.json \
      --artifact-evidence /path/to/evidence/uda-v2-static-staging.json \
      --artifact-evidence /path/to/evidence/uda-v2-node-artifacts.json \
      --out /path/to/evidence/uda-v2-combined-acceptance.json
    python -m pytest -q tests/test_combine_v2_fleet_acceptance.py

The combiner accepts only `static-staging-audit-v1` and
`node-static-artifact-audit-v1` evidence, requires
`production_modified=false` and `activation_allowed=false`, rejects duplicate
repositories, and changes a manifest REVIEW to final PASS only when artifact
PASS is bound to the exact fleet `v2_commit`. Missing or mismatched evidence
remains REVIEW; failed artifact evidence becomes FAIL. Even a 20 PASS combined
report keeps deployment and activation disabled and is not merge authority.

Final independent run on 19 November 2026:

- DAXBridge V2 commit `3f849761673d86f006173c3d0af668a352e546e8`:
  lockfile v3, Node 22/npm 10, zero moderate-or-higher npm audit findings,
  43 tests passed, production build passed, four public artifact files passed.
- Flowchain Studio V2 commit `184ba2d6b50244a3c2fdfab8694f52238ef5f5fc`:
  lockfile v3, Node 22/npm 10, zero moderate-or-higher npm audit findings,
  60 tests passed, production build passed, six public artifact files passed.
- Node artifact audit: **3 PASS / 0 REVIEW / 0 FAIL**.
- Source-only fleet: **14 PASS / 6 REVIEW / 0 FAIL**, as designed.
- Commit-bound combined acceptance: **20 PASS / 0 REVIEW / 0 FAIL**.
- Focused regression suite: **29 passed** across fleet, static, Node artifact and
  combined-evidence tests.
- UDA PR #27 CI passed on Ubuntu 22.04 and 24.04. Flowchain Studio PR #3 CI
  passed. DAXBridge PR #5's GitHub-hosted job did not start: GitHub reported an
  account payment/spending-limit failure before any workflow step. Its 43-test
  independent run and build passed, but the repository CI check remains an
  external release blocker until billing is restored and the workflow reruns.

The DAXBridge review also removed an unnecessary Markdown file from the public
Vite tree. Its required `catalogs/default.tsv.gz` is accepted only at that exact
path and is size-bounded, decompressed, UTF-8/TSV checked and sensitive-signature
scanned by the artifact verifier. Arbitrary gzip files remain forbidden.
