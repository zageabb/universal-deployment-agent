# Development Status

Last reviewed: 2026-11-17
Current development state: ACTIVE

## Purpose
Common development ledger for the user and AI agents. Existing project-specific planning documents remain valid; this file standardises status and completion evidence.

## Current objective
Reliable local application deployment, service visibility, grouping, health/status, configuration and operations.

## Existing planning and evidence sources
- `README.md`
- `UBUNTU_PORTS.md`
- `docs/`
- `tests/`

## Status values
- 🔵 PLANNED
- 🔨 IN PROGRESS
- 🚫 BLOCKED
- ⏳ AWAITING ACCEPTANCE
- ✅ COMPLETE
- 💤 DEFERRED

## Evidence standard
COMPLETE requires applicable repository evidence: implementation, changed files/non-empty diff, tests or recorded no-test reason, passing tests, CI where available, commit/PR evidence, intended-branch merge, and separately recorded external/user acceptance.

For coding work, an empty result, no write/edit action, unchanged branch HEAD, empty diff or missing requested validation means the task is not complete.

## Development ledger

### DEV-022 — UDA V2 controlled maintenance acceptance on m901-lenovo
Status: ⏳ AWAITING ACCEPTANCE
Priority: High
PR: #26 (draft; no merge/production activation)
Accepted technical test scope: read-only/review-only V2 integration at pinned
commit `1433ad57d0a5e45b6b0b536783181dda25fa63e7`.

Maintenance evidence (19 November 2026, approved 18:00–19:00 GMT;
execution 18:01–18:06 UTC):
- [x] Approved host maintenance window executed with controlled timer isolation.
- [x] Independent isolated regression passed: **491 passed in 35.40s**
      using Python 3.10.12 at the pinned PR #26 commit.
- [x] Both production timers restored enabled/active; no lock holder or
      temporary test unit, process, checkout or virtualenv remains.
- [x] SheetBridge, UDA dashboard and UDA home healthy (HTTP 200);
      public SheetBridge route continued redirecting HTTP 302 to UDA login.
- [x] Caddy healthy, valid configuration, unchanged Caddyfile SHA-256.
- [x] Production UDA checkout reconciled clean at `d92621c8`, aligned
      with origin/main; seven modified and two untracked files preserved on
      `backup/pre-v2-maintenance-20261119-1801` at `3e42eda81e27b27a7ef71976802dc3081ad75744`.
- [x] Existing `db-migration` regression logged as unrelated exception:
      `test_unconfirmed_relationship_rejected` expected HTTP 400 but
      received HTTP 500 following unexpected database connection.
      Production deployment-agent oneshot still fails due to this issue.
- [x] Full evidence attached to PR #26 as issue comment 7017706825.
- [ ] Accountable production owner reviews exception, preserved checkout
      backup and review-only activation boundary.
- [ ] Explicit production-owner sign-off for merging PR #26 recorded.
- [ ] Any future V2 activation or automatic recovery separately approved.

Result: **CONTROLLED ACCEPTANCE PASS WITH RECORDED EXCEPTION**, not a
production merge/activation authorization. No automatic recovery enabled.

Evidence: `https://github.com/zageabb/universal-deployment-agent/pull/26#issuecomment-7017706825`
This maintenance gate is independent of PR #27 and of the 20 V2 manifest
conversions, whose static application reviews remain open.

### DEV-021 — Independent V2 static-artifact acceptance (six review items)
Status: ✅ TECHNICAL ACCEPTANCE COMPLETE — OWNER RELEASE SIGN-OFF PENDING
Priority: High
Branch: `feature/uda-v2-independent-validation`
PR: #27 (draft and unmerged; 20/20 technical acceptance at `0d8deaac840a7dd29073283c2320f626ff025d66`)
Independent manifest-only baseline: 19 November 2026 — 14 PASS, 6 REVIEW, 0 FAIL.
Commit-bound combined acceptance: 20 PASS, 0 REVIEW, 0 FAIL; UDA full regression
518 passed, 1 skipped; PR #27 CI green on Ubuntu 22.04 and 24.04.

Requirements and progress:
- [x] Create read-only immutable Git-tree artifact auditor for static V2
      candidates; never execute npm/build commands from manifest data.
- [x] Add local regression checks covering root publication, exposed source or
      secrets, generated artifact gaps, and symlinks (4 fixture tests passed).
Independent static-artifact audit result (19 November 2026):
- [x] Run static Git-tree auditor against PR #27 commit `f97f5a8`.
      Result: **0 PASS / 6 REVIEW / 0 FAIL**, exit 1 as designed;
      auditor regression tests: **4 passed in 2.40s**.
- [x] Confirm read-only inspection: no builds and no production changes.
- [x] Record source-tree exposure findings without treating them as leaked
      credentials: Wallpaper Studio had 3 public candidates and 5 flagged
      tracked files; Roundabout Designer 16 and 27; CueCraft 1 and 10.
      Each needs an allowlisted staging directory and verified server
      document root, excluding repo Git data, docs, tests and source/config.
- [x] Confirm all three generated `dist/` outputs are untracked in Git
      (zero committed output files): Should-Cost Next, DAXBridge and
      Flowchain Studio each require a pinned isolated build, asset inventory
      and safety review.
- [x] Collect commit-bound artifact/build acceptance evidence for all six and
      combine it without changing the conservative source-only reports.
      Final technical result: **20 PASS / 0 REVIEW / 0 FAIL**; deployment and
      activation remain explicitly disabled and merge sign-off remains separate.

The operator-provided report and complete JSON evidence are held outside
GitHub; no evidence attachments were published because separate publication
approval was not given. These results are recorded as summary only.

- [x] Implement an exact-file allowlisted staging script on the three
      static-root application V2 branches, with V2 output_dir changed to
      `build/uda-public`; original V1 manifests remain intact.
- [x] Independently run five offline staging regressions per application (15 passed); public inventories and localhost `/apps/` route smoke checks passed.
- [x] Harden Roundabout Designer `deploy/serve.sh` to reject an unstaged
      document root, and serve staged public files rather than repository root.
- [x] Extend and independently test reviewed staging parity; arbitrary path/command changes remain errors.
- [x] Independently compare staged script allowlists with committed HTML
      resource references and V2 policy declarations: Wallpaper Studio
      3 allowlisted files / 2 HTML refs, Roundabout Designer 16 / 15,
      CueCraft 1 / 0. All three source-level checks passed.
      This is not equivalent to executing staging or application tests.
- [x] Independently execute staging and regression on pinned disposable
      checkouts of Wallpaper Studio, Roundabout Designer, CueCraft and UDA.
- [ ] Inspect deployed URL asset resolution and exact published file inventory;
      compare effective live document root read-only via authorised Desktop.
- [x] Wallpaper Studio: independently verify 3-file staged output and localhost route (HTTP 200).
- [x] Roundabout Designer: independently verify 16-file staged output and localhost route (HTTP 200); live Caddy verification remains separate.
- [x] CueCraft: verify single-file HTML staging and localhost route (HTTP 200); full live browser acceptance remains separate.
- [x] Roundabout Designer: replace root-publication candidate with allowlisted staged output (independent artifact acceptance passed).
- [x] CueCraft: replace root-publication candidate with single-file staged output (independent artifact acceptance passed).
- [x] Inspect Node build reproducibility prerequisites: Should-Cost Next has
      `package-lock.json`, but DAXBridge and Flowchain Studio have no
      npm lockfile on their current V2 branches (source check 19 Nov 2026).
- [x] Add read-only source warning for missing npm lockfiles, and verify
      declared Python staging build scripts exist in Git trees.
- [x] Add `tools/verify_node_static_build.py` to inspect existing `dist/`
      outputs without running npm: inventory/hash public files, check asset
      base paths, missing assets, file types, symlinks, source maps, sensitive
      signatures and npm lockfile presence.
- [x] Independently run six fixture tests for `tools/verify_node_static_build.py`; Node artifact acceptance is 3 PASS / 0 REVIEW / 0 FAIL.
- [x] Produce isolated Node builds and run the post-build verifier with
      immutable source commits, clean build logs, file hashes and tests.
- [x] Generate and review pinned lockfiles for DAXBridge and Flowchain
      Studio in disposable development checkouts before any reproducible
      isolated build; keep changes in their own review branches.
- [x] Should-Cost Intelligence Next: independently build and audit `dist/`.
- [x] DAXBridge: independently build and audit `dist/` (43 tests passed).
- [x] Flowchain Studio: independently build and audit `dist/` (60 tests passed).
- [x] Re-run fleet and static audits against pinned repository commits; retain
      evidence and review source-map, asset base-path and secret exclusion.
- [x] Add commit-bound final evidence aggregation. Source fleet remains
      **14 PASS / 6 REVIEW / 0 FAIL** by design; verified artifact evidence
      closes those reviews to **20 PASS / 0 REVIEW / 0 FAIL** without granting
      deployment, activation or merge authority.
- [x] Verify UDA PR #27 CI and Flowchain Studio PR #3 CI green. DAXBridge PR #5
      GitHub CI was not executed because GitHub rejected the job before setup
      for an account billing/spending-limit failure; retain this as an external
      release blocker despite the passing 43-test independent run and build.
- [x] Obtain independent isolated technical acceptance for all 20 conversions at the tested commits.
- [ ] Resolve DAXBridge PR #5 CI billing/spending-limit failure and rerun CI successfully.
- [ ] Obtain explicit owner release/merge approval; no manifest merge or V2 production activation is authorised.

Evidence handling: final acceptance report and JSON files supplied in chat; they have
NOT been attached to GitHub because separate publication approval is outstanding.

Evidence and instructions:
- `docs/v2-independent-fleet-validation.md`
- `tools/validate_static_artifacts.py`
- `tests/test_validate_static_artifacts.py`
- Uploaded independent fleet report 2026-11-19 and its pinned JSON manifest SHAs.
- UDA PR #26 production activation remains separate and approval-gated.

### DEV-020 — V2 manifests for live UDA applications not representable in V1
Status: 🔨 IN PROGRESS — 11 executable drafts and 6 design-only holds (including ScreenCraft)
Priority: High
Branch: feature/uda-v2-review per executable application; design-review branches for blocked special cases
Depends on: V2 schema/semantic validator and independent validation tooling in UDA PR #27
Integration status: review-only authoring, independent V2-only acceptance pending; production activation prohibited

Scope:
- Prepare review-only `uda.v2.yaml` candidates for the 17 live/enabled UDA
  registrations that lacked faithful V1 manifests, using the 17 November
  UDA deployment inventory and V1 gap reports plus current GitHub source.
- Preserve the actual service graph, build/runtime tools, systemd ownership,
  Docker/container data volumes, health checks, proxy authentication and
  secret references. Never infer missing credentials, irreversible migration
  rollback, backups, or live-host-only configuration.
- Build manifests on isolated feature branches and open draft PRs; do not
  replace existing V1 manifests, install services, run migrations, reload
  Caddy, alter the production registry, or silently enable auto-update.
- Keep UDA integration PR #26 and production maintenance acceptance as
  separate gates. GitHub Actions are not required: use independent validation.

DEV-020 execution update — 19 November 2026:
- [x] Tender Designer source inspected for Flask web entrypoint, independent
      mailbox daemon, launchers, venv requirements, SQLite and uploaded-file
      persistence, and named production environment requirements.
- [x] Tender Designer review-only V2 candidate committed in
      `zageabb/tender_designer` at `1b2cd7635aecb1a573b00a0e20213211b7c73de0`;
      draft PR #23 against `main` is open.
- [x] Static source checks: required top-level fields, allowed top-level keys,
      service declarations, explicit deployment approval and auto-update
      disabled. These are *not* equivalent to canonical schema validation.
- [ ] Run canonical UDA V2 JSON Schema and semantic validator against Tender
      Designer candidate, then isolated repository regression tests.
- [ ] Use ChatGPT Desktop for **read-only** effective systemd, Caddy, registry,
      SQLite/data ownership, secret-name and backup verification on
      `m901-lenovo`; never copy secret values.
- [ ] Confirm the declared admin credential mode, service unit ownership,
      mailbox lease/health semantics and production group before acceptance.
- [ ] Keep Tender Designer PR #23 draft/unmerged, with no migrations, live
      deployment or V2 activation.
- [x] Lucky Lab source reviewed: Compose container, port 5020, SQLite
      `server-data:/data` persistent mount, Dockerfile and startup sequence.
- [x] Lucky Lab V2-only manifest and safety review documented on
      `zageabb/lucky-lab-slot-statistics` draft PR #2 at
      `cc461730074f1692183f29ed9b93599f790a7839`.
- [ ] **CRITICAL Lucky Lab blocker:** current `docker-entrypoint.sh` runs
      `flask db upgrade` and `flask main seed` every start. Split these
      into separately approved operations with backup/restore evidence
      before any deployment; V2 may not activate this image as-is.
- [ ] Run canonical V2 schema/semantic and independent isolated checks on
      both Tender Designer and Lucky Lab; host verification read-only.
- [x] Bank of Mum V2-only review candidate committed on
      `zageabb/Bank_of_mum` draft PR #22 at `7b5ab3623874e20510e9c87d7d4aa3eb9cb6e2c4`.
      Active runtime is FastAPI + Next.js (legacy Flask must not be deployed);
      backend/Next versions, health paths and lockfile are source-backed.
- [x] Context Studio V2-only review candidate committed on
      `zageabb/context-studio` draft PR #6 at
      `86e0f70bbcaaa09c3de00a0d30df1f3e738a62dc`.
      Documented dual systemd runtime must be reconciled with current
      Vinext/Cloudflare frontend before acceptance.
- [ ] **CRITICAL Bank of Mum:** backend import auto-runs create_all,
      Phase 2/3 schema/data migrations and immutable trigger installation.
      Require reviewed migration split, backups and explicit DB approval.
- [ ] **CRITICAL Context Studio:** backend import runs create_all and managed
      migrations; Vinext start port/base path and Cloudflare bindings have
      not been shown compatible with the live Ubuntu runtime.
- [ ] Validate both new V2 manifests using canonical UDA schema/semantic
      checker and disposable application builds/tests; source review alone
      is not independent acceptance.
- [ ] Compare effective live systemd, Caddy, registry, SQLite locations and
      secret reference names with ChatGPT Desktop in read-only mode.
- [ ] Continue remaining eight first-phase V2-only manifests without
      loosening the draft/explicit-approval gates.

Phase 1 — draft from existing repository + UDA report evidence (12):
- Tender Designer — web and mailbox worker; verify worker health.
- Lucky Lab — Compose/container lifecycle; verify persistent-data policy.
- Bank of Mum — Node frontend and Python API; verify two service health targets.
- Context Studio — Node/Python services and custom proxy subpath routing.
- Research Core — Python library with no long-running service.
- Sidecar — container lifecycle and named persistent volume.
- ScreenCraft — app/PostgreSQL container graph and secret-backed proxy assertions.
- NetworkBridge — API, worker, Node UI build, discovery/router capabilities.
- SheetBridge — Python service, Node build and proxy assertion boundary.
- Should-Cost Intelligence — Alembic migrations and service dependencies.
- LedgerOne — Flask database upgrade, migration compatibility and rollback.
- Bottle Factory Game — static artifacts and separately approved legacy
  underscore-path alias/asset migration.

DEV-020 continuation — 19 November 2026:
- [x] Create review-only `research-core` Python library V2 manifest
      (no service or HTTP port), plus source/consumer verification notes;
      draft PR `zageabb/research-core#2`, commit `4d2573b`.
- [x] Create review-only `SideCar` Docker V2 manifest, backed by Git
      Compose and Dockerfile evidence; draft PR `zageabb/SideCar#3`,
      commit `4d0a288`. Existing named Docker volume and production
      PIN/secret must be reviewed; development defaults are not acceptable.
- [x] Add `tools/validate_v2_only.py` for V2-only immutable source,
      canonical schema and semantic inspection (no V1 parity requirement,
      no manifest command execution); add five disposable fixture regressions.
- [ ] Independently run the new V2-only validator/regressions against six
      candidate repositories, and resolve any reported schema/source failures.
- [ ] Compare live UDA registry, systemd/Docker/Caddy, secret **names**, and
      persistence/backup evidence read-only via ChatGPT Desktop before
      accepting any candidate.
- [ ] Resolve all startup auto-migration and container data-ownership
      blockers; no database writes or recovery actions without explicit approval.
- [ ] Continue remaining six Phase-1 V2-only application drafts.
- [ ] Re-run all independent UDA regressions and CI on the changed PR #27
      head; its earlier 518-pass baseline does not cover these new changes.

Historical 19 November DEV-020 checkpoint: **6 of 17 applications drafted** at that point;
none accepted, merged or deployed.

DEV-020 continuation — 19 November 2026 (next increment):
- [x] Review `NetworkBridge` source, API/worker systemd samples, Vite
      lockfile and SQLite initialization. Draft `uda.v2.yaml` +
      `docs/uda-v2-review.md` at `zageabb/NetworkBridge#44`,
      commit `4027399488327be202289cbb5ebf4734006db436`.
- [ ] **NetworkBridge blocker:** API lifespan and monitoring worker
      both initialise/write SQLite schema. Require independently reviewed
      migration/data retention, real host service ownership and separate
      router-polling/discovery permissions. No polling activated.
- [x] Review `ScreenCraft` Compose/PostgreSQL/Flask graph and create
      design-only blocker document in draft `zageabb/ScreenCraft#38`,
      commit `e05a257d311fa1cd2d0a7bc9f7862cb459639ec0`.
- [ ] **ScreenCraft blocker:** current Compose PostgreSQL image uses
      unpinned `postgres:17-alpine`, and the app Docker entrypoint
      runs Alembic upgrades automatically. Verify immutable image digest,
      persistent volume and SSO trust contract, separate database migrations
      and secure restore evidence BEFORE drafting an executable V2 manifest.
- [x] Harden read-only V2-only validator to report malformed YAML as
      an inspection failure rather than crash.
- [ ] Independently run canonical V2 schema, semantic, source checks and
      fixture regressions on the **seven** executable V2-only candidates;
      do not claim acceptance based on draft PRs or CI from prior commits.
- [ ] Follow up with additional source-backed V2-only drafts, keeping
      production activation and merges separately approval-gated.

Historical 19 November checkpoint: **7 of 17 executable candidates**, plus
**1 design-only blocked case** (ScreenCraft). None has completed
independent V2-only acceptance. No production changes executed.

DEV-020 continuation — 19 November 2026 (SheetBridge and LedgerOne):
- [x] Draft source-backed SheetBridge V2 service/build/SSO manifest at
      `zageabb/Sheetbridge#30`, commit
      `81e65df3178a0a5d0ab2d12f561a63342c3a4e4c`.
      FastAPI loopback port 5100, Vite npm lockfile, protected UDA group
      and proxy-secret reference; optional SQLite form storage remains
      unenabled and requires separate backup review.
- [x] Draft LedgerOne V2 Flask service manifest at `zageabb/LedgerOne#54`,
      commit `2d453a82cd27235307c5d90826367b176cc42eb5`.
      The source development launcher and port must be reconciled with
      actual production WSGI, database and accounting-document storage.
- [ ] **LedgerOne blocker:** app creation can auto-create schema and seed
      administrator/organisation. Confirm production settings, independent
      backups, accounting/audit integrity and explicitly governed migrations;
      never substitute development passwords or secret defaults.
- [ ] **SheetBridge gate:** verify actual Caddy assertion + SSO identity,
      group, effective PYTHONPATH and frontend release path. Determine if
      SQLite form storage is active before any stateful deployment.
- [x] Extend `tools/validate_v2_only.py` registry to nine review-only
      executable V2 candidates (still no V1 parity or host mutation).
- [ ] Independently execute canonical schema/semantic checks for all nine
      candidates using pinned checkouts; source-only review is not PASS.
- [x] Draft both remaining straightforward Phase-1 applications (Bottle
      Factory and Should-Cost); ScreenCraft remains design-only blocked.
- [ ] Proceed with 5 special/partial evidence cases after source checks.

Historical 19 November checkpoint: **9 of 17 executable V2 manifests** plus
**1 design-only blocked case** (ScreenCraft). No new candidate accepted,
merged or deployed.

DEV-020 Phase-1 authoring checkpoint — 19 November 2026:
- [x] `bottle_factory_game` review-only static V2 manifest and documented
      source blockers committed in draft `zageabb/bottle_factory_game#9`
      at `5d064c4f5afaf01eddd219d1cd4d75b6089193f5`.
- [ ] **Bottle Factory blockers:** npm lockfile absent; source-only
      `npm ci` must refuse until lockfile is reviewed. Existing app route
      `/apps/bottle_factory_game/` differs from V2 canonical hyphen slug;
      require separately approved alias or migration and Vite asset rebuild.
- [x] `should-cost-intelligence` Flask V2 draft and review checklist
      committed in `zageabb/should-cost-intelligence#48`
      at `1426afe554d4b323a9889290d9fd6abcd1cf5983`.
- [ ] **Should-Cost blocker:** Flask factory calls schema initialization;
      verify explicit migrations, SQLite/estimator/evidence preservation,
      source-pinned research-core build and effective production WSGI.
- [x] Register both new repos in the no-V1 read-only
      `tools/validate_v2_only.py` validator.
- [ ] Independently run schema, semantic, source/build checks and fixture
      regressions against **11** pinned V2-only candidate repos.
- [ ] Resolve ScreenCraft's design-only safety hold before creating its
      executable manifest. Do not invent a PostgreSQL SHA or run Alembic.
- [ ] Proceed to five DEV-020 Phase-2 special cases only after reviewing
      ownership, database and runtime evidence for each.

Historical Phase-1 milestone: **11/12 executable manifests**
and **ScreenCraft design-only review**. DEV-020 overall: **11/17**
executable candidates; no candidate independently accepted, merged or
deployed. Existing 20-app acceptance applies only to its pinned commits.

DEV-020 Phase-2 special-case design review — 19 November 2026:
- [x] Source-backed design-only Camper Power Studio review at
      `zageabb/camper-power-studio#1` (draft). Its host-inventory web
      port 5077 differs from local Next dev port 5075, and its wrapper
      installs dependencies then spawns API/Next processes. Confirm the
      effective supervisor process graph before assigning V2 ownership.
- [x] Source-backed DB Migration read-only/migration boundary review
      at `zageabb/DB_Migration#68` (draft; changelog updated). No generic
      executable manifest or database-write capability inferred from repo.
- [x] ShadowPrompt Lab secure exposure and external action review at
      `zageabb/shadowprompt_lab#1` (draft). Unprotected Flask, potentially
      sensitive audit/output files and approval-gated email require
      substantial security gates before UDA publication.
- [x] Application Home + UDA protected self-upgrade joint ownership
      design recorded at
      `docs/v2-dev020-platform-ownership-review.md` on UDA PR #27.
      Both belong to one existing UDA installation. No duplicate Home
      lifecycle owner or self-managed bootstrap is authorised.
- [ ] Before executable V2 manifests for these special cases:
      independent read-only host ownership/service/volume/identity
      reconciliation, separate approved runtime graph and backup/restore
      evidence. Do not loosen deployment or database-write gates.
- [x] Add opt-in disposable `tools/prepare_v2_only_workspace.sh` for
      the exact 11 review branches (refuses existing output; source clone only);
      document operator-run independent validation and private evidence paths.
- [x] Read-only GitHub source inspection of all 11 draft YAML manifests
      against current V2 JSON Schema structural constraints: **11/11
      with no schema-shape findings**. This lightweight structural check
      is NOT an independently executed Python JSON Schema + semantic run.
- [x] Correct research-core V2 library isolation/verification declaration,
      and explicit persistent volume lifecycle owners in Lucky Lab and
      SideCar; commits `716df8b`, `dba124b`, `4068ca6`.
- [x] Extend V2-only independent validator with 11 app-specific machine-
      readable `REVIEW_GATE` categories, preserving migration/SSO/volume/
      lockfile/runtime hold status even when schema/source checks succeed.
- [x] Add four further Python regressions (canonical library and persistent
      volume semantic acceptance/rejection; per-repository risk inventory;
      review gate reporting). **Tests committed, execution pending.**
- [ ] Run pinned eleven-candidate V2-only canonical schema/semantic/source
      validation and the complete UDA regression suite, recording results
      outside GitHub until explicit evidence-publication approval.
- [ ] Complete the ScreenCraft executable graph only after real pinned
      PostgreSQL digest, Alembic startup split, persistent volume and
      trusted UDA identity contract have been reviewed.

**Coverage:** 17/17 registration cases now have at least initial source-backed
review or design. **Executable draft manifests: 11/17** (no V2-only technical
acceptance); **design-only safety holds: 6/17** (ScreenCraft plus five
special ownership/runtime cases). This is NOT deployment readiness.
The 20 previously accepted V1→V2 conversions remain a separate pinned
acceptance population.

DEV-020 validator continuation — 20 November 2026:
- [x] Verified UDA PR #27 draft and cleanly mergeable at previous
      `eb1b7bd` before changes; GitHub recovery workflow success on
      that commit does **not** establish eleven-app validator acceptance.
- [x] Improve `tools/validate_v2_only.py` to stop and return FAIL for
      schema-invalid nested YAML without dereferencing malformed nodes.
- [x] Explicitly hold `npm ci` candidates with missing committed npm
      lockfiles at REVIEW (no build invocation).
- [x] Add two disposable Git regression fixtures covering malformed YAML
      and lockless `npm ci` source references.
- [ ] Run the updated V2-only test fixtures and the complete UDA regression
      suite independently on the current UDA HEAD. No new test-pass result
      is claimed merely because test files were committed.
- [ ] Run canonical V2 schema/semantic/source checks on eleven pinned app
      checkouts, retain private reports, and fix findings on draft branches.
- [ ] Preserve explicit production owner approval and release gates;
      do not activate UDA V2 while data, router, SSO and lifecycle
      reconciliations remain open.

DEV-020 Bottle Factory follow-up — 20 November 2026:
- [x] Bottle Factory `zageabb/bottle_factory_game#9` independently
      reported commit `fc5db0258102729e3b03798541c0fabe4a4f6e3c` with
      tracked npm lockfile v3 (SHA-256
      `9927bc1c0b10dec745fdb88b624fcdc69d0ce6d817bfe150d74141906528b9e0`).
      Operator reported `npm ci`, 21/21 tests and Vite production build PASS,
      and 20/20 independent V2-only validator regressions PASS.
- [x] Remove stale static `NPM_LOCKFILE_MISSING` warning from UDA
      `REVIEW_GATES`. Missing lockfiles are determined dynamically from
      the pinned Git tree. Add a regression checking a committed lockfile
      does not emit a missing-lockfile warning.
- [ ] **Security release gate:** operator's `npm audit` identified
      1 moderate + 1 high Vite/esbuild advisory. Investigate
      `GHSA-67mh-4wv8-2f99` and `GHSA-587h-7wmj-h5pm`,
      assess runtime-vs-development exposure, and test a controlled
      compatible upgrade without automatically applying Vite 8.3.8.
- [ ] Keep `LEGACY_UNDERSCORE_ROUTE` gate: deployed
      `/apps/bottle_factory_game/` differs from proposed canonical
      `/apps/bottle-factory-game/`; approve alias or asset/base migration
      separately before any activation.
- [ ] Rerun new UDA regression additions on current PR #27 head;
      the reported 20/20 result predates these additional test changes.
- [ ] Current Bottle Factory acceptance remains REVIEW, not FAIL or PASS:
      source and lockfile checks clear, but security and URL/host gates remain.

DEV-020 Bottle Factory security follow-up — 20 November 2026:
- [x] Re-confirm draft `zageabb/bottle_factory_game#9` lockfile head
      `fc5db025` before changes; independent operator tests passed,
      but npm audit reported one high and one moderate vulnerability.
- [x] Check upstream advisories: esbuild GHSA-67mh-4wv8-2f99
      patches at >=0.25.0; launch-editor/Vite
      GHSA-587h-7wmj-h5pm has a Vite 6.4.4 backport. Vite 6.4 is
      still a supported security maintenance line as of review date.
- [x] Add Bottle Factory offline `scripts/check-v2-static-artifacts.mjs`
      verifying canonical V2 asset URL, required file presence, excluded
      source maps and restricted publication contents, plus 3 offline
      fixture tests; update Actions to `npm ci` and build with the
      canonical V2 prefix. **New checks not yet independently executed.**
- [x] Update Bottle Factory `docs/uda-v2-review.md` to distinguish
      resolved lockfile from open security issue; document disposable
      Vite 6.4.6 candidate upgrade and full `npm ci` / tests / build /
      static audit / `npm audit` requirements. No dependency upgrade
      applied, no override/--force, no production activation.
- [ ] Independently run new static-artifact fixtures and a disposable
      Vite 6.4.x migration trial. Confirm clean audit and browser/gameplay
      at `/apps/bottle-factory-game/` before changing lockfile again.
- [ ] Continue to hold `DEPENDENCY_AUDIT_REMEDIATION` and
      `LEGACY_UNDERSCORE_ROUTE` in UDA validator until evidence clears.
- [ ] Verify combined UDA PR #27 latest-head tests and GitHub CI;
      prior success is commit-specific, not current-head evidence.

DEV-020 Bottle Factory Vite 6 trial automation — 20 November 2026:
- [x] Added `scripts/trial-vite6.sh` to Bottle Factory draft PR #9,
      providing opt-in disposable Vite 6.4.6 dependency resolution,
      exact lockfile/proposed diff capture, `npm ci`, tests,
      canonical-prefix static build, artifact checker, all/dev-free npm
      audits and resolved-dependency inventory.
- [x] Added three no-network fail-closed guard fixtures for omitted,
      existing and unsafe result directories; test execution still pending.
- [x] Documented the trial and evidence-publication boundary in
      `zageabb/bottle_factory_game/docs/uda-v2-review.md`.
- [ ] Run the trial independently in a network-capable, unprivileged
      disposable environment. Current ChatGPT runtime has no GitHub/npm
      DNS and no cached Vite 6.4.6; **no successful upgrade run exists**.
- [ ] Re-review proposed package and lockfile changes, moderate/high
      audit advisories, browser gameplay, static security and base path.
      Only then commit a verified dependency upgrade to PR #9.
- [ ] Preserve Bottle Factory V2 REVIEW gates: dependency audit remediation,
      legacy underscore path transition and independent host acceptance.
      No build, migration, deployment or live proxy changes authorised.

DEV-020 Bottle Factory independent static fixture regression — 20 November 2026:
- [x] Run an isolated local source reconstruction of Bottle Factory V2
      static-artifact checker and eight fixture tests (Node 22.16.0):
      **8 passed, 0 failed**; no npm packages or network required.
- [x] Extend draft `zageabb/bottle_factory_game#9` checker to inspect
      single/double/unquoted HTML src/href, malformed percent encoding,
      traversal/backslashes and symlinked publication roots.
- [x] Correct GitHub-transfer escaping drift in the HTML regex and
      backslash guard at `7804060c`; document its difference from the
      isolated reconstruction. Do not conflate local fixture tests with
      full GitHub-head package install/build evidence.
- [ ] Run independent `npm ci`, 21 gameplay tests, static build and npm
      audit on exact PR head in network-capable isolated environment.
- [ ] Reconcile old underscore proxy URL and complete Vite 6.4 security
      upgrade before removing `DEPENDENCY_AUDIT_REMEDIATION` or
      `LEGACY_UNDERSCORE_ROUTE` from the UDA V2 acceptance gates.

DEV-021 — UDA V2 Approval Centre initial implementation (20 November 2026):
- [x] Add `approval_centre.py`: persistent private SQLite review request
      register and audit events, exact source SHA, 1–168-hour expiry,
      create/approve/deny/revoke transitions, no command execution.
- [x] Add `/approvals` page, registered-app request and CSRF-protected
      decision routes to existing admin-authenticated `dashboard.py`;
      add dashboard navigation and dedicated accessible review/audit tables.
- [x] Display the eleven V2-only source-backed `REVIEW_GATES` visibly
      without treating review approval as validation or clearing holds.
- [x] Add `tests/test_approval_centre.py` including CRUD transitions,
      expiration, file permissions, admin authentication, CSRF, static
      gate preservation, underscore legacy names and no-service-execution
      fixture. Tests committed; **full Flask/pytest run not yet executed**.
- [x] Document trust model and staged acceptance in
      `docs/v2-approval-centre.md`. This is an administrative review
      record, NOT a signer or revocation authority for existing V2 tokens.
- [ ] Independently run the new Approval Centre tests and full UDA
      regression suite on this exact PR #27 head, with relevant dependencies.
- [ ] Implement independent per-person identity/role attribution,
      sealed durable audit and stronger multiple-process concurrency if
      required by deployment security review.
- [ ] Provide a read-only unified gate feed for the earlier twenty
      V1→V2 conversions and six special design-only cases; current
      source-backed gate list covers only eleven V2-only drafts.
- [ ] Separately design trusted, cryptographic token revocation enforcement.
      This UI must never grant execution rights based on a SQLite bit.
- [ ] Approve protected production storage/backup/role ownership and
      deploy through normal release gates; draft feature not activated.

DEV-021 Approval Centre independent backend check and full DEV-020 inventory — 20 November 2026:
- [x] Independently reconstruct Approval Centre backend from PR #27 in a
      disposable Python 3.13.5 workspace: **8/8 passed** on SQLite;
      lifecycle, deny, revoke, expiry, invalid commit, underscore legacy
      name, 5-way concurrent decision (only one success), private
      permissions and symlink rejection.
- [x] Add `tools/v2_design_holds.py` for six special design-only cases:
      ScreenCraft, Camper Power Studio, DB Migration, ShadowPrompt Lab,
      protected UDA self-upgrade and Application Home.
- [x] Add read-only section to Approval Centre so DEV-020 shows
      **11 executable manifest review candidates + 6 design-only holds**.
      Source metadata is not live host state or a deployment authority.
- [x] Add PR regression tests for concurrent approval, SQLite privacy,
      6/6 design holds and UI visibility; execution of these *new*
      full-repository tests remains pending.
- [ ] Run full dashboard Flask integration + UDA suite on checked-out
      PR #27 head with installed dependencies; GitHub Actions billing
      blocker still prevents treating CI as execution evidence.
- [ ] Map twenty earlier V1→V2 conversions and live approvals into a
      read-only unified inventory without allowing a UI review record
      to bypass trusted signed execution authority.

Phase 2 — special/partial evidence (5):
- Camper Power Studio — compare host-only supervisor wrapper and both processes;
  do not invent service entrypoints.
- DB Migration — verify PostgreSQL dependency, schema/readiness and separately
  approved database-write capability, without exposing credentials.
- Application Home — resolve shared UDA lifecycle/component ownership; no
  independent app manifest or duplicate service owner without design approval.
- Universal Deployment Agent — bootstrap-only, externally supervised self-upgrade;
  ordinary self-deployment must remain blocked.
- ShadowPrompt Lab — reconcile missing WSGI source/entrypoint before producing
  an executable service declaration.

Ownership and location of V2 manifest work (required workflow):
- **ChatGPT + GitHub — primary development:** Read the existing V1 manifests,
  repository build files, source entrypoints and canonical V2 schema. Create
  V2 manifests in the application repositories on dedicated feature branches,
  validate them and run independent tests. GitHub remains the source of truth;
  ChatGPT Desktop is not required to author the manifests.
- **ChatGPT Desktop — deployment verification:** Compare candidate manifests
  against `m901-lenovo`'s effective systemd units, Docker configuration,
  UDA registry and Caddy routing. Collect secret *names*, never secret values.
  Start with read-only verification. Any state-changing acceptance remains
  separately approval-gated.
- **UDA — future activation:** Discover and validate V2 manifests only until
  the production installer is explicitly approved. Installation, migration
  and recovery each require explicit production authorisation; manifest
  existence or successful schema validation never grants execution rights.

Phase 3 — independent validation and host verification:
- Extend the read-only fleet runner (`tools/validate_v2_fleet.py`) to accept
  these V2-only candidates and compare against recorded live-deployment
  evidence, rather than assuming a V1 parity baseline.
- Run YAML, canonical V2 JSON Schema, UDA semantic graph, source-file, security,
  and permission checks; obtain immutable source SHAs and evidence reports.
- Run build/runtime checks only in an approved disposable sandbox; do not
  execute arbitrary manifest commands on `m901-lenovo`.
- Use ChatGPT Desktop / the authorised operator for read-only comparison with
  effective systemd, Docker, Caddy, env-variable names, data ownership and
  health. GitHub remains the canonical source of truth.
- Mark unresolved assumptions as REVIEW/BLOCKED, not PASS, and keep every PR
  in draft until the relevant independent acceptance and sign-off are recorded.

Point 4 — workflow acceptance checklist (where V2 manifests are built):
- [ ] ChatGPT + GitHub: review each applicable V1 manifest, repository
      build files, source entrypoints and V2 schema before generating V2.
- [ ] ChatGPT + GitHub: commit candidates to per-repository feature branches,
      run independent schema/semantic/source tests and record draft PR evidence.
- [ ] ChatGPT Desktop: read-only compare each candidate against effective
      m901-lenovo systemd units, Docker settings, UDA registry and Caddy routes.
- [ ] ChatGPT Desktop: record secret reference names only (never values) and
      flag unresolved live-host differences for explicit review.
- [ ] UDA: implement manifest discovery and validation without treating a
      discovered manifest as executable or auto-activated.
- [ ] UDA: enforce separate explicit production approval gates for installation,
      database migration and interrupted-transaction recovery.
- [ ] Retain review evidence and keep V2 candidate/PR deployment disabled
      until the relevant approvals and independent acceptance are recorded.

Completion criteria:
- [ ] 12 phase-1 V2 candidates drafted, independently validated, and raised
      as draft PRs with no production activation.
- [ ] 5 special-case designs resolved or explicitly blocked with evidence.
- [ ] Fleet validator extended for V2-only candidates and independently tested.
- [ ] Per-repository source, runtime/security, data/migration, health and proxy
      discrepancies recorded and reviewed.
- [ ] Production sign-off separately recorded before any deployment or merge.

Evidence inputs:
- `uda-manifest-inventory.md` (17 November 2026, 50 UDA registry entries).
- `uda-v1-deployment-gap-reports.md` (16 contract/deployment model gaps plus
  ShadowPrompt Lab source mismatch).
- `docs/v2-independent-fleet-validation.md` and UDA draft PR #27.


### DEV-018 — Repository-based application onboarding
Status: 🔨 IN PROGRESS
Priority: High
Branch: \`feature/repository-onboarding\`
Integration status: safe discovery and installation preview implemented; full install engine pending

Requirements:
- Register new GitHub-hosted applications without needing ChatGPT Desktop to
  clone code, create service definitions, or maintain the UDA registry manually.
- Standard root \`uda.yaml\` manifest for a preview of runtime, build, service,
  proxy, environment variables and deployment preferences.
- Administrator-approved and transactionally recoverable installation.
- No sync to the live server until combined releases are tested and accepted.

Current implementation:
- Implements frozen uda.yaml v1.0 schema in `schemas/uda-manifest-v1.schema.json`, matching Application-Standard `standards/schemas/uda-manifest-v1.schema.json`; unknown nested keys are rejected, and runtime version/working directories stay in the signed staging plan.
- Restricts repository URLs to HTTPS GitHub and records exact source SHA.
- Clones \`--no-checkout\` temporarily and reads only \`uda.yaml\`.
- Limits manifest size, rejects unsafe YAML/invalid fields and validates
  branch choice, service entrypoint, group/proxy basics and port requests.
- Generates an installation plan, allocates a candidate port, and checks UDA registry conflicts.
- Adds authenticated, CSRF-protected dashboard preview and signed 15-minute approval tickets.
- Administrator-approved staging revalidates the exact SHA/plan, then clones into an isolated directory without executing repository-defined commands.
- Inactive release preparation packages staged files under a commit-specific path, records SHA-256 digests, detects tampering and renders a systemd service *preview only*.
- Authenticated private repository staging retrieves pinned commits through the GitHub API with per-blob integrity checks and bounded snapshot size.
- Optional rootless Podman build worker enforces offline, read-only source, restricted resources and separate approval; remains disconnected from production activation.
- A disabled UDA registry entry and deterministic activation/rollback plan can be previewed without changing production.
- A separate transaction coordinator implements lock/snapshot/preflight, compensation-before-mutation, health/SSO/runtime attestation ordering and rollback failure reporting.
- Append-only fsync journal captures state and pending compensation intent without persisting raw error/secret values; rollback continues even when journal persistence fails.
- Durable private recovery snapshots preserve the exact pre-activation registry, unit, proxy and attestation files; incomplete transaction scanner and explicitly approved reverse replay added.
- Fail-closed worker policy ensures no repository manifest, dashboard configuration or review-only recovery check can enable a privileged production adapter.
- File-backed adapter uses atomic registry/unit/proxy/attestation replacement and injected systemd/health/SSO callbacks; production callbacks/dashboard activation remain disabled.
- Fail-closed activation preflight checks release integrity, service/port collisions, approval flags and protected environment files; returns an auditable rollback checklist without enabling execution.
- Does not install services, update the registry, execute builds or change Caddy.

Evidence:
- Source: \`onboarding.py\`, \`templates/onboarding.html\` and
  \`tests/test_onboarding.py\`.
- Documentation: \`docs/repository-onboarding.md\`.
- Tests pushed but full independent suite and CI are **NOT VERIFIED**.
- Remaining: privilege-separated production worker, audited recovery replay and
  restart-time orchestration, wiring build approvals and real systemd/Caddy callbacks,
  final port reservation, large-source/LFS policy and live Ubuntu acceptance.

### DEV-017 — UDA deployment identity and GitHub reporting
Status: 🔨 IN PROGRESS
Priority: High
Branch: `feature/deployment-reporting`
Integration status: implementation pushed; independent regression validation pending

Requirements:
- Show local checkout, remotely tracked branch and attested deployed commit separately.
- Identify modified/hybrid server installations and block misleading deployment reports.
- Report releases to each application's own GitHub Deployments API, not UDA only.
- Keep publication off by default, require health and no source commits.
- No ChatGPT MCP dependency and no live server changes before controlled synchronisation.

Evidence:
- `deployment_reporting.py` implements read-only inventory, optional release receipt
  and opt-in publisher.
- Dashboard displays distinct running/checkout/remote SHA and dirty warnings.
- `tests/test_deployment_reporting.py` covers key cases.
- `docs/deployment-reporting.md` contains configuration and rollout guidance.
- Full pytest, CI merge gate, runtime validation, GitHub publication acceptance:
  **NOT YET COMPLETE**.
- Known follow-up before enabling periodic reporting: publication idempotency
  and durable audit/retry history.

### DEV-016 — Archive and restore registered applications
Status: 🔨 IN PROGRESS
Priority: High
Owner/Agent: Codex
Branch: `feature/archive-restore`
Integration status: isolated and regression-tested; ready for review, merge and live acceptance

Requirement:
- Let an administrator make an application dormant without deleting its UDA
  registry entry, then restore the same registration later.

Implementation:
- The authenticated, CSRF-protected dashboard action changes the existing
  `enabled` flag while holding the deployment lock.
- Service applications are stopped/disabled when archived and enabled/started
  when restored. UDA-managed scheduled jobs are reconciled and published proxy
  routes are refreshed. Library entries only change registry state.
- Service entries without `service_unit` are rejected because UDA cannot safely
  control their runtime.

Evidence:
- Files: `dashboard.py`, `templates/dashboard.html`, operations/configuration
  documentation and dashboard regression tests.
- Tests: `PYTHONPATH=. python3 -m pytest -q` — 116 passed.
- Recovery source: `backup/server-state-2026-11-17` preserves the original live
  server implementation before this clean branch was prepared from current main.
- Merge, deployment and external/user acceptance: pending.

### DEV-015 — Return authenticated users to protected applications
Status: ⏳ AWAITING ACCEPTANCE
Priority: High
Owner/Agent: Codex
Branch: `main`
Integration status: implemented and regression-tested; live acceptance pending

Requirement:
- Replace the initial proxy 401/error page with a safe login redirect and return
  users to the originally requested application after authentication.
- Treat duplicate login submissions as success once the first request has
  already established the session.

Implementation:
- `/auth/check` validates the forwarded original URI and redirects anonymous
  browsers to the login form with a local-only return path.
- The login endpoint redirects authenticated duplicate submissions without
  rechecking their stale CSRF token.
- Generated Caddy routes explicitly reconstruct the published prefix after
  `handle_path` processing and forward the original URI. Routes can also add a
  validated server-controlled proxy assertion from Caddy's environment.

Evidence:
- Files: `home.py`, `proxy_config.py`, documentation and regression tests.
- Tests: `PYTHONPATH=. python3 -m pytest -q` — 111 passed.
- Live anonymous probe: `/apps/screencraft/?from=login-test` returned HTTP 302
  to `/login?next=/apps/screencraft/?from%3Dlogin-test` after Caddy reload.
- Live authenticated browser: ScreenCraft refreshed without an error page and
  retained the existing owner project. Duplicate-form user acceptance remains
  pending.

### DEV-014 — Repair live portal user-management template
Status: ⏳ AWAITING ACCEPTANCE

Restored the tracked `portal_users.html` on the Ubuntu host after the stale
runtime copy linked to a nonexistent invitation endpoint. The authenticated
`/admin/users` page rendered successfully after restart.

### DEV-013 — Repair live groups page template
Status: ⏳ AWAITING ACCEPTANCE

Restored the tracked `groups.html` on the Ubuntu host after the stale runtime
copy linked to a nonexistent assignment endpoint. Authenticated `/groups`
returned HTTP 200 after restart.

### DEV-012 — Register Should-Cost Intelligence Next prototype
Status: ⏳ AWAITING ACCEPTANCE

Registered the private React/Vite prototype for automatic updates, with
`auto_deploy: true`, branch `main`, systemd service on port 5091, and the
`TAIJU` home-page group. Live UDA advanced it from `ad4467e` to `536e202`; build,
restart and health validation succeeded. The app is not published through Caddy.
The broader UDA run can still report failure due to unrelated Allocraft tests.

### DEV-011 — Read repository visibility from GitHub
Status: ⏳ AWAITING ACCEPTANCE

The 5030 dashboard and 5048 launcher resolve each checkout's GitHub `origin`
and query current repository visibility when building application lists.
Private lookups use `UDA_GITHUB_TOKEN` from the protected service environment;
the registry value remains the offline fallback. On Ubuntu the live lookup for
`should-cost-intelligence-next` returned `private`; the token file is mode 0600.

### DEV-010 — Direct per-user application assignments
Status: ⏳ AWAITING ACCEPTANCE
Priority: Medium
Owner/Agent: Codex
Branch: `main`
Integration status: implemented and test-verified; live acceptance pending

Requirement:
- Allow the same application to be assigned directly to multiple individual
  people without changing its UDA or portal group.

Implementation:
- The identity database gains a backward-compatible `apps_json` entitlement
  column. User detail and invitation forms expose published applications.
- Effective access is the union of group and direct assignments, and both the
  portal directory and Caddy authorization endpoint use the same decision.

Evidence:
- Files: `portal_auth.py`, `home.py`, user detail/invitation templates,
  documentation and regression tests.
- Tests: `PYTHONPATH=. ~/.local/share/deployment-agent/venv/bin/python -m pytest -q` — 103 passed.
- User/business acceptance: pending.

Completion criteria:
- [x] Implementation exists.
- [x] Relevant files changed.
- [x] Regression tests added.
- [x] Relevant tests pass.
- [ ] Commit evidence recorded and pushed to `main`.
- [ ] Live schema migration and access forms verified.
- [ ] External/user acceptance separated from development completion.

### DEV-009 — Separate proxy portal groups from operational UDA groups
Status: ⏳ AWAITING ACCEPTANCE
Priority: Medium
Owner/Agent: Codex
Branch: `main`
Integration status: implemented and test-verified; live acceptance pending

Requirement:
- Let a published application appear in a user-facing portal group while
  retaining its existing development/server group in UDA operational screens.

Implementation:
- Optional `proxy_group` controls only Application Home display placement and
  falls back to `group` for display. When explicitly set it is also the effective
  portal/Caddy entitlement; entries without it retain the legacy `allowed_groups`
  policy. The group manager exposes separate UDA and portal group assignments and
  keeps both consistent across rename/delete operations.

Evidence:
- Files: `ui_groups.py`, `home.py`, `dashboard.py`, `deploy_agent.py`, group
  management template, registry example, configuration documentation and tests.
- Tests: `PYTHONPATH=. ~/.local/share/deployment-agent/venv/bin/python -m pytest -q` — 102 passed, including portal/Caddy authorization parity.
- User/business acceptance: pending.

Completion criteria:
- [x] Implementation exists.
- [x] Relevant files changed.
- [x] Regression tests added.
- [x] Relevant tests pass.
- [ ] Commit evidence recorded and pushed to `main`.
- [ ] Live UDA group management and portal rendering verified.
- [ ] External/user acceptance separated from development completion.

### DEV-008 — Administrator-provisioned user invitations
Status: ⏳ AWAITING ACCEPTANCE
Priority: Medium
Owner/Agent: Codex
Branch: `main`
Integration status: implemented and test-verified; live acceptance pending

Requirement:
- Allow administrators to assign application groups before a person requests an
  account, without choosing or handling that person's password.

Implementation:
- The user directory includes an administrator-only invitation form with group
  selection. UDA creates an unverified account, sends a one-time 24-hour
  activation link, and verifies the account only after the recipient chooses a
  password. Failed email delivery removes the incomplete account.

Evidence:
- Files: `home.py`, `portal_auth.py`, `install.sh`, user and account templates,
  `tests/test_home.py`, `tests/test_portal_auth.py`.
- Tests: `PYTHONPATH=. ~/.local/share/deployment-agent/venv/bin/python -m pytest -q` — 98 passed.
- User/business acceptance: pending.

Completion criteria:
- [x] Implementation exists.
- [x] Relevant files changed.
- [x] Regression tests added.
- [x] Relevant tests pass.
- [ ] Commit evidence recorded and pushed to `main`.
- [ ] Live administrator form and activation-page rendering verified.
- [ ] External/user acceptance separated from development completion.

### DEV-007 — Separate user directory and access detail pages
Status: ⏳ AWAITING ACCEPTANCE
Priority: Medium
Owner/Agent: Codex
Branch: `main`
Integration status: implemented and test-verified; live acceptance pending

Requirement:
- Replace the long combined user-access form with a scannable user directory
  and a dedicated account/access page for each user.

Implementation:
- `/admin/users` lists account identity, administrator status and verification
  state; `/admin/users/<email>` displays and updates only the selected account.
- Existing administrator authorization, CSRF checks, group validation and user
  update semantics are retained.

Evidence:
- Files: `home.py`, `install.sh`, `templates/portal_users.html`,
  `templates/portal_user_detail.html`, `static/home.css`, `tests/test_home.py`.
- Tests: `PYTHONPATH=. ~/.local/share/deployment-agent/venv/bin/python -m pytest -q` — 96 passed.
- User/business acceptance: pending.

Completion criteria:
- [x] Implementation exists.
- [x] Relevant files changed.
- [x] Regression tests added.
- [x] Relevant tests pass.
- [ ] Commit evidence recorded and pushed to `main`.
- [ ] Live authenticated list/detail flow verified.
- [ ] External/user acceptance separated from development completion.

### DEV-006 — Selective asset-prefix stripping
Status: ⏳ AWAITING ACCEPTANCE

Base-path-aware applications may generate prefixed asset URLs while their
runtime asset server only accepts root-relative `/assets/*` requests. The proxy
generator now supports validated `proxy_strip_prefix_paths` handlers before the
preserved application route. Tests cover ordering and configuration injection.

### DEV-005 — Automatic safe proxy migration monitor
Status: ⏳ AWAITING ACCEPTANCE
Priority: High
Owner/Agent: Codex
Branch: `main`
Depends on: DEV-003 migration contract
Can run in parallel with: individual application migrations
Integration status: integrated, installed, enabled and live-validated

Requirement:
- Detect newly deployed UDA subpath-compatible applications and safely publish
  them without merging branches or changing application code.

Implementation:
- A locked systemd timer validates the migration marker, clean/current checkout,
  complete repository test suite, live forwarded-prefix response, atomic registry
  update, Caddy reload and fail-closed public ingress.
- Registry and routes roll back automatically when publication validation fails.

Evidence:
- Files: `proxy_migration_agent.py`, `tests/test_proxy_migration_agent.py`,
  systemd service/timer, installer, README and this ledger.
- Tests: `PYTHONPATH=. ~/.local/share/deployment-agent/venv/bin/pytest -q` — 88 passed.
- Dry run: detected the newly deployed Should Cost Intelligence migration and
  passed its complete repository suite and forwarded-prefix backend probe.
- Live run: automatically published Should Cost Intelligence, reloaded Caddy,
  retained the unauthenticated 401/403 boundary and passed authenticated root,
  static asset, knowledge and settings checks.
- Timer: `uda-proxy-migration.timer` enabled and active on a ten-minute interval.
- Commit: `cc2d7e8`, pushed to `main`.
- User/business acceptance: pending.

Completion criteria:
- [x] Implementation exists.
- [x] Relevant files changed.
- [x] Tests added.
- [x] Relevant tests pass.
- [x] Dry-run correctly identifies current registry state.
- [x] Timer installed and live execution validated.
- [x] Commit evidence recorded and pushed to `main`.
- [ ] External/user acceptance separated from development completion.

### DEV-004 — Support authenticated LAN and public portal login
Status: ⏳ AWAITING ACCEPTANCE
Priority: High
Owner/Agent: Codex
Branch: `main`
Depends on: DEV-002
Can run in parallel with: application subpath migrations
Integration status: integrated, installed and live-validated

Requirement:
- Permit the same Application Home service to authenticate through its explicit
  trusted-LAN HTTP address while retaining secure cookies through public HTTPS.

Implementation:
- Trust the reverse proxy's forwarded scheme and select the session cookie's
  `Secure` attribute from the effective request scheme.
- Preserve `HttpOnly` and `SameSite=Lax` for both access paths.

Evidence:
- Files: `home.py`, `tests/test_home.py`, `README.md`, `DEVELOPMENT.md`
- Tests: `PYTHONPATH=. ~/.local/share/deployment-agent/venv/bin/pytest -q` — 85 passed.
- Commit: `a098d7a` (implementation), merged to and pushed on `main`.
- Live validation: LAN HTTP sets a non-`Secure` host cookie; public HTTPS sets a
  `Secure` host cookie. Both retained CSRF state and handled a test login POST.
- User/business acceptance: pending.

Completion criteria:
- [x] Implementation exists.
- [x] Relevant files changed.
- [x] Tests added.
- [x] Relevant tests pass.
- [x] Commit evidence recorded.
- [x] Merged to `main`.
- [x] Live LAN and public HTTPS login flows validated.
- [ ] External/user acceptance separated from development completion.


### DEV-003A — Motorbike Cost Tracker auto-migration redirect probe
Status: 🔨 IN PROGRESS

The live Motorbike Cost Tracker redirects from `/` to its login route. The proxy migration agent was following that redirect to an as-yet-unpublished external UDA route and blocking publication. Validate the first backend response without following redirects, accept only redirects remaining inside the candidate's authenticated application mount, and reject external hosts/unsafe paths. Tests: `tests/test_proxy_migration_agent.py`. Public proxy remains disabled until live checks succeed; no app settings changed.

- [x] GitHub CI green and merged to main: PR #6, commit d4af1b0
- [ ] UDA installed/updated and run against live Motorbike Cost Tracker
- [ ] UDA agent status + Caddy authorization checked

### DEV-003 — UDA-listed application subpath migration
Status: 🔵 PLANNED
Priority: High
Owner/Agent: per-app assignment pending
Depends on: service/repository mappings, framework audit and DEV-002 proxy acceptance
Integration status: 36-entry live UDA allowlist captured; individual application migrations not started

Requirement:
- Modify **only applications listed in the live UDA registry** so their browser front ends work beneath `/apps/<slug>/`. An unlisted GitHub project is excluded even if it is a web application.
- Record exact repo-to-UDA-entry mapping, runtime/framework, port, route slug, URL behaviour and permission groups before edits.
- Preserve current LAN/root-mode usability, authentication boundary, cookies, API/streaming routes and storage.
- Apply `docs/app-subpath-migration.md` framework-specific acceptance checks; migrate and validate one listed app at a time.

Evidence:
- Specification: `docs/app-subpath-migration.md`
- Registry membership: owner supplied live UDA list of 36 enabled entries, recorded in `docs/uda-registry-migration-inventory.md` (33 launcher-visible, 2 hidden infrastructure, 1 without launcher URL; only CatManager published). Exact slug/repo mapping still pending per-app verification.
- Application changes, CI and live Caddy checks: not started.
- User acceptance: pending.

Completion criteria:
- [x] Owner-supplied live UDA registry inventory recorded as a fixed 36-entry allowlist.
- [ ] Each listed hosted app audited and changes made where necessary.
- [ ] Framework-specific automated regression coverage passes.
- [ ] UDA/Caddy auth and prefix end-to-end checks pass.
- [ ] Per-app commits/CI and acceptance recorded.


### DEV-002 — Authenticated application portal and controlled ingress
Status: ⏳ AWAITING ACCEPTANCE
Priority: High
Owner/Agent: Codex
Branch: `main`
Integration status: implementation verified locally; live deployment pending final external prerequisites

Requirement:
- Email-based registration, verification and password reset; per-user UDA group
  entitlements; proxy-side enforcement; and explicit registry-controlled publication.

Implementation:
- SQLite identity store and portal routes in `portal_auth.py` and `home.py`.
- Administrator user/group assignment page.
- Caddy configuration generator publishes only `proxy_enabled` applications.
- UPnP registration utility maintains only the fixed 80/443 ingress mappings.

Evidence:
- Files: `portal_auth.py`, `proxy_config.py`, `home.py`, templates, tests and docs.
- Tests: `python -m pytest -q`.
- User/business acceptance: pending.

### DEV-001 — Generic GitHub Actions workflow trigger
Status: ✅ COMPLETE
Priority: High
Owner/Agent: ChatGPT Desktop
Branch: `main`
Depends on: Authenticated GitHub CLI with Actions write permission
Can run in parallel with: Application-specific development
Integration status: integrated and installed

Requirement:
- Provide a generic UDA-accessible command that explicitly dispatches a named
  GitHub Actions workflow for a repository/ref, discovers the resulting run,
  reports structured status, and can wait for completion.

Implementation:
- `github_ci.py` exposes `trigger_ci(repo, workflow, ref)` and the installed
  `uda-trigger-ci` command.
- Authentication remains with GitHub CLI; UDA does not store GitHub tokens.

Evidence:
- Commit: `8e20e00` (implementation); this ledger update records live evidence
- PR: direct main integration requested for the live UDA installation
- Files: `github_ci.py`, `tests/test_github_ci.py`, `install.sh`, `README.md`,
  `docs/operations.md`, `DEVELOPMENT.md`
- Tests: `python3 -m pytest -q` — 80 passed
- CI: `zageabb/wallpaper` workflow `ci.yml`, run `37310292793`, completed
  successfully at commit `1adb42180f08517e3079937518f20c0ecf27aa2d`.
- Merged to intended branch: yes, UDA `main` at `8e20e00`
- User/business acceptance: pending

Completion criteria:
- [x] Implementation exists.
- [x] Relevant files changed.
- [x] Tests added/updated.
- [x] Relevant tests pass.
- [x] Real workflow dispatch demonstrated.
- [x] Commit evidence recorded.
- [x] Merged to `main`.
- [x] External/user acceptance separated from development completion.

### DEV-000 — Establish evidence-based development ledger
Status: ✅ COMPLETE

Evidence:
- Files: `DEVELOPMENT.md`, `AGENTS.md`
- Git history records these changes.
- Tests: not required for this documentation/process-only change.
- User acceptance: requested 2026-10-02.

## New item template

### DEV-XXX — Short title
Status: 🔵 PLANNED
Priority: Medium
Owner/Agent:
Branch:
Depends on:
Can run in parallel with:
Integration status:

Requirement:

Implementation:

Evidence:
- Commit:
- PR:
- Files:
- Tests:
- CI:
- Merged to intended branch:
- User/business acceptance:

Completion criteria:
- [ ] Implementation exists.
- [ ] Relevant files changed.
- [ ] Tests added/updated, or reason recorded.
- [ ] Relevant tests pass.
- [ ] CI passes where applicable.
- [ ] Commit/PR evidence recorded.
- [ ] Merged where required.
- [ ] External/user acceptance separated from development completion.

Notes:

## Parallel development coordination

Use the coordination fields on every active DEV item when parallel work is possible.

- **Owner/Agent** — the person or AI agent currently responsible for the item.
- **Branch** — the working branch or worktree used for the item.
- **Depends on** — DEV items, decisions or external prerequisites that must complete first.
- **Can run in parallel with** — DEV items that are safe to develop concurrently without conflicting ownership or sequencing.
- **Integration status** — for example: not started, isolated, ready for integration, integrated, or integration blocked.

Before starting parallel work, agents should check these fields and avoid claiming the same item, branch or overlapping integration responsibility. If two items touch the same subsystem or files, record the conflict explicitly and sequence or coordinate integration rather than assuming they are independent.

Parallel execution does not weaken the completion standard: each DEV item still requires its own implementation, tests/validation, CI evidence where applicable, and integration/merge evidence before it can be marked COMPLETE.

## Maintenance rule
Update this file during the same development pass that changes implementation. Repository evidence wins when prose disagrees.

## V2-002 — version-aware read-only repository inspection (17 November 2026)

- Added `onboarding_v2.py` version dispatcher: V1 retains existing 32 KiB validation and stage-only path; V2 has a bounded 128 KiB strict schema plus semantic graph validation.
- GitHub manifest remains read at a pinned commit SHA by the existing secure discovery workflow; V2 previews validate declared source branch and repository.
- Dashboard `/onboarding/preview` renders a redacted V2 deployment graph: workloads, health, toolchains, dependencies, database/volume policy, authenticated ingress, environment variable **names**, and protected capabilities.
- V2 never issues a staging ticket, never calls V1 port allocator, and never presents a stage/activate button; its plan explicitly denies execution and staging.
- Existing registered applications or port conflicts are flagged for reconciliation, not modified; no actual live-service unit discovery or OS probing occurs yet.
- Canonical v2 design is still draft Application-Standard PR #6; schemas and validator copied to this branch for testing, not for a supported production v2 installer.
- Test evidence: UDA [V2-002 CI run 44187103836](https://github.com/zageabb/universal-deployment-agent/actions/runs/44187103836) passed Python 3.12 and 3.13, **80 passed each** (`tests/test_onboarding.py`, `tests/test_onboarding_v2.py`, `tests/test_dashboard.py`). Compilation checks also passed.
- Risk/next gate: read-only unit/Caddy/Compose/volume reconciliation and actual disposable Ubuntu V2-003 multi-service deployment acceptance remain pending. No production changes. V2 never authorises migration or UDA bootstrap.

