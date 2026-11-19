# UDA-DEPLOY-002 — Repository-based onboarding

Development stage: **versioned v1 manifest validation, approved source staging and activation components implemented; production installer still disabled**.

## Purpose

An administrator opens **UDA → Install from GitHub**, supplies an HTTPS GitHub
repository URL and branch, and receives a plan derived from the repository's
root `uda.yaml` manifest. This removes the manual inspection step from
ChatGPT Desktop. UDA does not yet apply the installation plan.

## Versioned uda.yaml v1.0 contract

The canonical authoring specification is maintained in the
[Application-Standard repository](https://github.com/zageabb/Application-Standard/blob/main/standards/UDA_MANIFEST_v1.md)
and the schema at `standards/schemas/uda-manifest-v1.schema.json`.
UDA vendors the same schema at `schemas/uda-manifest-v1.schema.json` and
enforces it during manifest discovery. Both source files must remain byte
identical at release.

Schema v1.0 rejects unknown keys, validates runtime combinations, bounded
argv build/service commands, relative working directories, environment
variable names, secure proxy policy, and requested deployment booleans.
Optional `runtime.version`, `runtime.working_dir`, and
`build.working_dir` are preserved in signed staging plans and checked
again before source staging. Version strings are currently informational;
they do **not** guarantee a matching interpreter or Node runtime has been
provisioned.

Application-Standard provides `templates/uda.yaml` and schema contract
tests. The specification is frozen for application authors but remains
subject to CI/review before merging into the standard repository.


## V2-003: disposable real systemd SIGKILL and recovery inspection (19 November 2026)

The `tests/integration/v2_systemd/crash_acceptance.py` integration harness
uses the real UDA V2 `save_recovery_evidence`,
`DurableServiceJournal` and `plan_interrupted_recovery` modules against
**two hard-coded test services** in a disposable Ubuntu systemd-PID1
container. It does **not** implement privileged production deployment or
automated recovery.

- The separate, network-disabled Ubuntu **22.04 and 24.04** CI jobs build
  their own test-only Docker images. Each has an isolated Python virtual
  environment with a compatible `jsonschema` API, because Ubuntu 22.04's
  distribution version lacks `Draft202012Validator`.
- The test starts the web and worker services, saves their actual unit-file
  bytes and running status, durably journals a `restore:web` intent, then
  replaces only the `uda-v2-test-web.service` unit file and issues a
  `systemctl daemon-reload`.
- The update subprocess kills **itself** with `SIGKILL`; a new process
  verifies the persisted snapshot, complete SHA-256 chained journal and
  exact expected compensation target.
- The UDA recovery preflight provides **review-only** actions. The parent
  verifies that inspection did not change the modified unit. The test
  harness then explicitly stops its two disposable services, restores
  their original unit bytes and running states, and verifies HTTP health.
- The workflow uploads version-specific evidence artifacts. It uses a
  privileged Docker container only on an ephemeral GitHub-hosted runner;
  `--network none` and no production mounts keep the test away from
  Caddy, UDA registry, production service accounts and application DBs.
  Never run this workflow against a production Docker daemon.

**Successful acceptance:** [run 44557629274](https://github.com/zageabb/universal-deployment-agent/actions/runs/44557629274)
passed for both Ubuntu versions.

**Limitations:** This verifies process death during a real *test* systemd
unit-file update, not power loss, host reboot or an actual authenticated
UDA installer. The integration fixture explicitly restores its own test
services; UDA **does not** yet replay recovery automatically or support
production activation. A separately authenticated, least-privilege host
worker and approved maintenance-window testing are still required.

## V2-003: actual SIGKILL and read-only recovery after restart (19 November 2026)

`tests/test_onboarding_v2_process_crash.py` and
`tests/fixtures/v2_crash_child.py` verify that durable pre-mutation
snapshots and a chained journal survive an abrupt **OS SIGKILL** of an
independent Python subprocess. All files are created inside a disposable
private temporary sandbox, and only fake service callbacks are used.

- In one test a child is killed after a successful fsynced snapshot but
  **before** any configuration change. The restarted process sees the old
  bytes and a review-required state with no invented compensation steps.
- In another test the child is killed **after** overwriting the first
  isolated unit file. Its recovery journal contains the previously fsynced
  `intent:restore:web`, and a new process can identify the exact
  transaction, reviewed unit mapping and prior running states.
- A fresh Python interpreter independently reloads both evidence files
  and returns a manual-only recovery plan. The inspection does **not**
  restore any files or start/stop any service.
- A deliberately truncated journal after crash fails validation. The
  execution flag and automatic recovery permission remain **false**.
  No Caddy, production UDA registry, live systemd or database is touched.

**Verified CI:** [V2-003 Process Crash Recovery Evidence run 44554504064](https://github.com/zageabb/universal-deployment-agent/actions/runs/44554504064)
passed **189 tests** on both Python 3.12 and Python 3.13, including
prior snapshot-first, journal, approval, parser and simulated-worker tests.

This is **process-crash evidence acceptance**, not proof of host power
loss durability or reboot recovery, and not a trusted replay worker.
Remaining: disposable systemd integration with abrupt process failure,
operator-authorized recovery, host privilege boundaries and a controlled
host acceptance procedure. The new 22.04/24.04 matrix enhancement on
draft PR #21 must be integrated into the stacked chain before final merge.

## V2-003: snapshot-first offline worker rehearsal (19 November 2026)

`onboarding_v2_worker_rehearsal.py` now integrates the read-only recovery
snapshot from PR #22 into the simulated multi-service transaction:

- Validates the private snapshot directory and transaction UUID before
  consuming a one-use reviewed-bundle token.
- Under the existing exclusive sandbox service lock, captures **all** old
  unit-file bytes and prior running states, and calls the new coordinator
  `before_mutation` hook to persist a transaction-bound, fsynced snapshot.
- The durable journal records a `snapshots_persisted` transition after the
  snapshot callback succeeds and **before** any `configure` or `start`
  effect can run.
- The snapshot binds the exact reviewed bundle SHA, source commit, service
  identity and service-to-unit mapping. Existing transaction evidence cannot
  be overwritten.
- A failed snapshot write, duplicate transaction, invalid UUID or exposed
  snapshot directory fails closed without unit changes. Test injection verifies
  no fake service callback runs if snapshot persistence fails.
- The operation remains a **sandbox-only offline rehearsal**; its review
  approval still carries no authority to modify real systemd units or recover
  an interrupted installation automatically.

**CI evidence:** [V2-003 Snapshot Before Mutation run
44541266799](https://github.com/zageabb/universal-deployment-agent/actions/runs/44541266799)
passed **184 tests on both Python 3.12 and 3.13** with the snapshot-first
integration, invalid-path/duplicate-transaction and failed-persistence
regressions.

**Outstanding:** process-kill/reboot tests, authentic approval-to-execution
protocol, host-locked production unit adapter, source/identity attestation and
post-crash manual compensation. The SHA-256 local snapshot is not an external
signature. Production activation and automatic replay remain disabled.

## V2-003: interrupted transaction recovery preflight (19 November 2026)

`onboarding_v2_recovery_preflight.py` adds private, immutable-once
**pre-mutation snapshot evidence** and a strictly **read-only** interruption
review to the v2 service-graph prototype:

- Stores original per-unit bytes and prior running status in a private
  snapshot file using exclusive-create, fsync and directory fsync. The
  snapshot is keyed to a UUID transaction, reviewed application, pinned
  source SHA, unit-bundle digest and explicit service-to-unit mapping.
- Validates the entire existing SHA-256 chained journal, the exact
  transaction identity, snapshot hashes, declared service ownership,
  and pending intent membership before producing an operator checklist.
- Returns the pending compensation intents in reverse order with explicit
  service and unit names, and the old running state. It never runs systemctl
  or a recovery action. A completed healthy/degraded/rolled-back journal
  produces no recovery steps.
- Rejects snapshot/journal corruption, wrong bundle or source commit,
  unknown service names, changed unit mappings, duplicate snapshot IDs,
  and exposed or symlinked snapshot roots.
- The result always declares `can_execute: false` and
  `automatic_replay_allowed: false`. A snapshot hash is **not** a trusted
  external signature or substitute for independently authenticated approval.

**CI evidence:** [V2-003 Interrupted Recovery Preflight run
44517881090](https://github.com/zageabb/universal-deployment-agent/actions/runs/44517881090)
passed **180/180 tests on Python 3.12 and 3.13**, including preceding V1/V2
approval, renderer, sandbox, journal, systemd parser and rehearsal tests.

**Still pending:** integration of snapshot persistence into the real
transaction worker **before** unit mutation, durable authorisation and
source/ownership attestation, safe resume after process or host restart,
actual privileged worker isolation, and disposable host crash/reboot tests.
No production deployment or recovery route has been enabled.

## V2-003: disposable Ubuntu 24.04 real systemd lifecycle acceptance (18 November 2026)

The `tests/integration/v2_systemd/` integration harness now exercises the
actual systemd service manager, not just mocked lifecycle callbacks or the
`systemd-analyze verify` parser. It runs **only** in a GitHub-hosted, ephemeral
Ubuntu 24.04 Docker systemd-PID1 environment:

- Workflow `.github/workflows/v2-disposable-systemd.yml` builds the CI-only
  Ubuntu image, starts a network-disabled container with private `/run`,
  copies hard-coded `uda-v2-test-web.service` and
  `uda-v2-test-worker.service` fixtures, then executes the test inside that
  container. The container uses `--privileged` for systemd PID1 and must
  remain restricted to ephemeral GitHub-hosted CI; **never run this CI command
  against the production Docker daemon**.
- The test script refuses to run unless `UDA_V2_DISPOSABLE_CONTAINER=1`,
  `/.dockerenv` exists, PID 1 is systemd and the OS is Ubuntu 24.04.
  Its command helper permits only the hard-coded two test service names.
- Real `systemctl` starts the web service, confirms a local HTTP health
  endpoint, then starts its dependent worker and confirms its heartbeat.
- Stopping the optional worker demonstrates that the application remains
  healthy at the web tier but must be recorded as **degraded**.
- The test snapshots both real unit-file bytes and their running states,
  deliberately replaces the web unit launcher with a failing command,
  detects the failed service, restores both previous unit definitions,
  reloads systemd and restores the prior web/worker running states.
- Unit files and the entire disposable container are torn down at the end.
  Machine-readable evidence is uploaded as a short-retention CI artifact.
  No host volume, Docker socket, network connectivity, Caddy configuration,
  UDA registry, project database or actual application is mounted or touched.

**Verified CI acceptance:** [V2-003 Disposable Ubuntu Systemd Lifecycle
run 44350066025](https://github.com/zageabb/universal-deployment-agent/actions/runs/44350066025)
completed **successfully**. The job log confirms
`PASS: disposable systemd startup, degraded worker and rollback`; the
`uda-v2-disposable-systemd-evidence` artifact contains per-stage results.

**Scope warning:** This integration harness directly controls two **CI-only
systemd units**. It is not wired to the UDA manifest installer and is not a
production deployment worker. It does not yet prove recovery through an
unexpected host reboot, privilege separation of the future UDA worker,
authentication of production activation approvals, or deployment of an
actual 18-app manifest. Production activation remains disabled and the
entire V2 implementation stays in draft PRs.

## V2-003: actual Ubuntu systemd parser acceptance (18 November 2026)

`onboarding_v2_systemd_verify.py` extends the offline rehearsal with a real
**systemd syntax-validation** gate; it still does not activate services:

- Re-checks an immutable reviewed bundle's application/source identity,
  individual unit SHA-256 hashes, aggregate digest and exact unit allowlist
  before writing copies of unit files to a **private temporary** directory.
- Invokes only `/usr/bin/systemd-analyze verify` through a restricted,
  no-shell, bounded-output, timeout-limited subprocess. Paths must refer
  to the exact private workspace; arbitrary `systemctl` commands, unit
  restarts, SSH, sudo, Caddy, registry and database writes are forbidden.
- Verifies companion units together so the systemd parser can interpret
  declared `After` and `Requires` dependencies. Invalid unit text and
  parser errors do not produce syntax acceptance.
- Reports only names, hashes, syntax status and a diagnostic count; it
  never exposes raw unit commands, environment values or potentially
  sensitive parser output.
- Always reports `production_activation_allowed: false`. Passing syntax
  validation is **not** proof of runtime health, working service execution,
  privilege isolation, restart handling or recovery after host reboot.

**CI evidence:** [V2-003 Systemd Parser Acceptance run
44247285432](https://github.com/zageabb/universal-deployment-agent/actions/runs/44247285432)
passed **169 tests each on Python 3.12 and Python 3.13**, including a real
Ubuntu `systemd-analyze` 259 parser pass on a disposable two-service unit
graph and all preceding versioning, approval, worker-rehearsal and rollback
regressions.

Real isolated user-systemd deployment, restart/health, transaction snapshot
recovery, independent privileged-worker review, and disposable Ubuntu
end-to-end acceptance remain pending. No production activation is provided.

## V2-003: integrated offline worker rehearsal (18 November 2026)

`onboarding_v2_worker_rehearsal.py` composes the previously separate
verification, approval and rollback components into one **offline-only**
transaction rehearsal. It does **not** implement production service
installation or authorize a real systemd worker:

- Re-validates the full v2 systemd-only graph and independently prepared
  source-release SHA, Python runtime profile hashes, exact reviewed startup
  vectors, private environment-file references, and unit-bundle bytes.
- Rejects a bundle that differs from **freshly rendered source/runtime
  evidence**. The one-use review attestation must be bound to the exact
  bundle hash, reviewer, application and source SHA.
- Enforces `rehearsal_only: true`, a private temporary unit sandbox, a
  separate private durable journal directory, and an exact worker-to-unit
  allowlist. An invalid transaction ID is rejected **before** consuming the
  review token.
- Uses only injected **fake process callbacks** while writing isolated,
  atomic unit-file copies. It records review receipt, journal and snapshot
  evidence; required worker failure restores the previous unit bytes and
  running status, and optional worker failure reports `degraded`.
- A consumed review token cannot be reused for a second rehearsal. An
  unapproved reviewer, changed source, altered rendered unit or unknown unit
  blocks the operation without touching the simulated process state.
- Results always report `host_changes_allowed: false` and
  `production_activation_allowed: false`. The review receipt itself carries
  `permission: review_only`, **not** installation authority.

All tests use temporary filesystem paths and fake service callbacks; no
`systemctl`, sudo, SSH, Caddy, UDA registry, Docker, database or network
operations occur. This integration establishes an acceptance rehearsal, not a
production deployment adapter. Real Ubuntu activation still requires
independent operator authentication, restricted privilege boundaries, durable
snapshots plus crash recovery and disposable-host end-to-end acceptance.

## V2-003: reviewed Python virtualenv runtime profiles

`onboarding_v2_runtime_profiles.py` extends the **review-only** systemd unit
renderer to support a separately provisioned Python virtualenv launcher:

- A service may declare `[".venv/bin/python", "app.py"]` only if a
  **separately approved** `runtime_profiles[service_name]` is supplied to
  `render_reviewed_units`. The repository manifest cannot approve itself.
- A Python runtime profile binds the virtualenv's private absolute directory,
  its expected interpreter target, interpreter SHA-256, `pyvenv.cfg` SHA-256,
  and the prepared source commit. This accommodates the common virtualenv
  `bin/python` symlink only when it resolves to the exact independently
  reviewed executable.
- Render-time verification rejects symlink swaps, executable/config file
  modifications, source-commit changes, public-writable virtualenv directories,
  unknown workloads, non-Python services and unsupported `python -c` or
  shell launchers. Application scripts still must exist in the prepared,
  checksum-verified source release.
- Unit text contains the reviewed **absolute virtualenv executable path**,
  never an untrusted relative executable. The interpreter and config hashes
  are included in `runtime_hashes`, which are incorporated into the overall
  bundle digest. Consequently, changing runtime bytes while retaining the
  executable path **changes the review bundle identity**.
- `onboarding_v2_approval.py` checks the runtime evidence as part of the
  existing bundle signature. An old signed review cannot approve a changed
  runtime.
- No virtualenv creation, pip installation, package execution, dependency
  resolution, activation or production unit installation occurs. The runtime
  profile is a **review artifact**, not authorisation to run processes.

**Verification:** [V2-003 Runtime Profiles run 44243834473](https://github.com/zageabb/universal-deployment-agent/actions/runs/44243834473)
passed **148 tests on Python 3.12 and 148 on Python 3.13**. The initial run
detected a real bundle-hash omission for changed virtualenv interpreter bytes;
the renderer, approval verifier and tests were updated together before the
passing run.

Outstanding work includes application-specific wrapper policies, immutable
virtualenv build provenance, trusted host operator identity, actual restricted
systemd activation, crash restart recovery and disposable Ubuntu acceptance.

## V2-003: independently signed, single-use reviewed-bundle attestation

`onboarding_v2_approval.py` adds a **review-only** approval envelope for a
previously verified unit bundle. An independent operator authority, not the
UDA web dashboard or manifest, provides the signing key and authenticated
reviewer identity. The module intentionally exposes no HTTP signing endpoint.

- The HMAC-SHA256 attestation binds the **exact** application identity,
  pinned source commit SHA, reviewed unit-bundle digest, reviewer, purpose
  `review_unit_bundle`, and an unpredictable single-use nonce.
- Validity is limited to 15 minutes. A review is consumed through an
  exclusive-create receipt in an existing private directory (`0700`), with
  a `0600` file, fsync and directory fsync. Reuse is denied.
- The verifier re-hashes each unit text, checks the unit hashes and canonical
  bundle digest, rejects changed order/source identity and rejects another
  reviewer, wrong key, forged action, expiry or malformed envelope.
- Receipts record only review identity and bundle hashes, never entrypoint
  commands or environment values.
- A successful review returns `permission: review_only`,
  `can_install: false`, `can_start_service: false`, and
  `can_recover: false`. **Neither the token nor receipt is an activation
  authorization.** A separate, independently authenticated privileged worker,
  strict host policy and an activation-specific approval protocol are still
  unimplemented.

The review signing key and operator identity **must be provided by a trusted
out-of-band authority**. HMAC protects integrity and authenticity only while
this key remains secret. This mechanism alone does not enforce identity
authentication, nonrepudiation or permission for actual host mutations.
No dashboard or production service path calls the attestation component.

**CI evidence:** [V2-003 Review Approval Gate run
44198636614](https://github.com/zageabb/universal-deployment-agent/actions/runs/44198636614)
passed **134 tests on both Python 3.12 and 3.13**. This includes new
tampering, expiry, replay and scope tests plus preceding V1/V2 regressions.

## V2-003: pinned-source systemd unit review bundles

The `onboarding_v2_unit_renderer.py` increment generates deterministic
**non-executable systemd unit review artifacts** from a source-verified,
inactive release. It is not a privileged Ubuntu installer:

- Validates the manifest against the v2 schema and semantic graph and
  rejects protected UDA bootstrap, container/database operations, advanced
  routes and capabilities.
- Re-hashes the prepared release against its Git commit identity, rejects
  application mismatch, and ensures working directories/scripts exist within
  that verified release.
- Requires each service's exact `systemd_unit`, a separately provided
  independently reviewed argv tuple matching the manifest, and a unique,
  private environment-file reference. Disallows shell entrypoints, relative
  interpreter resolution and Python `-c`; this initial renderer supports
  only a narrow, explicitly allowed set of absolute interpreter paths.
- Renders bounded user-service unit text with `NoNewPrivileges`,
  `ProtectSystem`, `PrivateTmp` and related hardening; systemd argument
  quoting escapes newlines, special characters and percent specifiers.
- Resolves dependency order into `After`/`Requires`, calculates individual
  unit SHA-256 hashes and an overall bundle digest, and always returns
  `deployment_allowed: false` and `status: review_only`.
- Never writes unit files, issues a stage ticket, runs commands, changes a
  service, provisions secrets or edits the UDA registry/Caddy.

This deliberately narrow contract will not yet cover applications whose
launchers require virtual environments, wrappers, custom binaries or other
runtime layouts. They must remain blocked for review rather than bypass the
command policy. A future worker must verify the signed/approved bundle and
its source commit *again* inside an independently authenticated deployment
boundary.

**CI evidence:** [V2-003 Reviewed Unit Plans run
44197431558](https://github.com/zageabb/universal-deployment-agent/actions/runs/44197431558):
120 tests passed on each of Python 3.12 and 3.13, including prior sandbox,
journal, preflight, graph, and v1/v2 transaction regression tests. All code
is in unmerged development PR #16.

## V2-003: disposable unit-file adapter (development only)

`onboarding_v2_unit_sandbox.py` implements the injected simulation-adapter
contract against a private temporary filesystem sandbox. Unlike earlier
in-memory tests, this increment writes atomically to **test-only systemd-like
unit files** and captures their previous bytes and prior running status.

- Sandbox must be an existing private directory below the operating-system
  temporary root. Symlinks, hardlinked unit files, untrusted names and
  writable/exposed lock files are rejected.
- Atomic unit writes flush and fsync data and the parent directory.
- All start, stop, runtime-state and health operations are supplied as **fake
  test callbacks**, not systemctl commands. No dashboard endpoint calls this.
- Rollback restores the exact previous unit bytes and previous running
  state. A partial failed start or health probe triggers the simulator's
  full-service compensation path.
- The existing SHA-256 chained journal can be injected to record durable
  intent before each simulated mutation. Source command and secret values are
  not journalled.
- Fail-closed unit paths remain restricted to the sandbox. The module has
  no privileged Ubuntu worker, no Caddy or registry integration and no
  authority to install or modify any actual service.

**Test evidence:** [V2-003 Sandbox Unit Adapter CI run
44194945825](https://github.com/zageabb/universal-deployment-agent/actions/runs/44194945825):
**104/104 tests passed on Python 3.12 and 3.13**, covering this adapter
plus the preceding V2-003 preflight/journal and V1/V2 transaction regressions.

This is **not** production acceptance: a separately approved restricted
Ubuntu systemd worker, actual unit-file renderer and policy review,
operating-system isolation, restart-time recovery, integration tests and
an explicit deployment authorisation boundary are still required.

## V2-003: Ubuntu read-only reconciliation and crash-journal foundation

The multi-service simulated transaction coordinator is now accompanied by
two isolated, explicitly **non-activating** Ubuntu-side building blocks:

- `onboarding_v2_ubuntu_preflight.py`: schema-validated service graph inspection
  using only exact allowlisted, non-mutating `systemctl --user list-units` and
  `systemctl --user show` argument vectors. The output is bounded, limited to
  unit identity, load/state, unit-file location and working directory; source
  command lines and environment values are never requested. The checkout path
  must be provided by the trusted operator, not by the manifest. Missing
  declared units, repository-associated unregistered companions, lifecycle
  ownership disagreement and unverified source directories are **blocking
  reconciliation discrepancies**. This is intentionally separate from the
  repository-only v2 web preview; it does not SSH, restart units or modify the
  running UDA registry.
- `onboarding_v2_recovery_journal.py`: private `0700` journal root,
  `0600` append-only file, per-event fsync, SHA-256 chained records and bounded,
  allowlisted operation/state payloads. It rejects symlinked or exposed paths,
  modified records, truncation and noncanonical sequences. It retains no
  source commands, environment values or secrets. The recovery status reader
  reports outstanding undo intent for **manual review**, but
  `can_auto_replay` is always `false`.

The journal can be injected into the V2-003 in-memory transaction coordinator
for failure testing. It does **not** provide an independently authenticated
approval capability, automatic recovery after crash, a production systemd
installer, Caddy publication or a privileged worker identity. Chain hashes
detect accidental/unauthorised modification without a trusted external root;
they are not signatures and cannot prove authorship.

A real Ubuntu worker will still require a documented least-privilege unit
allowlist, atomic unit-file snapshots and restore, strict operator approval,
transaction-specific recovery binding, source-SHA attestation, health/readiness
checks, crash recovery, and disposable Ubuntu end-to-end acceptance before
any production activation route is enabled.

## V2-003: multi-service transaction simulation (development only)

The separate `onboarding_v2_multiservice.py` module now provides an
**injected-adapter, simulation-only** service-graph transaction for v2
`deployment.strategy: systemd` applications with explicit aggregate health.

- Parse and validate the canonical v2 service graph; reject cycles and
  unsupported deployment kinds, containers, databases, sensitive capabilities
  and complex proxy routes. There is no link from the dashboard or an
  installation route to the simulator.
- Acquire an injected exclusive lock and capture a snapshot of **every unit**
  before any configuration action.
- Execute named `configure` and `start` callbacks in dependency order.
  Before each effect, register an idempotent undo action and pass its intent
  to an injected **durable journal callback**. Callback failure blocks
  additional mutations.
- Check individual service health using the health type declared in v2.
  Required service failures cause **full release compensation**; optional
  worker probe failure marks the release `degraded`, not healthy.
- Reverse compensations in opposite order. Partial failure during
  `configure` or `start` is covered because undo is registered *before*
  invoking the adapter. Compensations that fail remain in `pending_undo`,
  and the result is `rollback_failed`; an incomplete rollback must never
  be reported as success.
- All audit records contain only service names, operation labels, status and
  error **types**. They do not persist source-authored command vectors or
  environment values.
- The result always declares `production_activation_allowed: false`.

**Test evidence:** V2-003 CI workflow
[run 44189808670](https://github.com/zageabb/universal-deployment-agent/actions/runs/44189808670)
passed **58 tests on Python 3.12 and 3.13**, including transaction failure
injection and existing onboarding/adapter regression tests.

This is **not a real systemd installer**. It has no privileged service
adapter, journal persistence provided by default, crash-recovery integration,
Caddy/SSO publication, real source preparation, health polling or deployment
receipt. Database migration, container, and UDA self-bootstrap pathways are
explicitly out of scope. Disposable Ubuntu acceptance and a separate trusted
approval boundary remain mandatory before a production integration.

## V2-002: version-aware read-only manifest inspection (development)

The GitHub repository onboarding reader now dispatches a root `uda.yaml` by
`schema_version` at the **exact selected commit SHA**:

- `schema_version: 1` continues to use the existing 32 KiB limit, full v1
  parser, stage-only preview, approval ticket and source staging workflow.
  Existing v1 repositories do not need their manifests changed.
- `schema_version: 2` is limited to 128 KiB and validated against the
  proposed v2 JSON Schema and the semantic graph validator from
  Application-Standard PR #6. The dashboard displays a **read-only graph**
  of named services and containers, build toolchains, health classifications,
  dependencies, data volumes, migrations count, proxy/SSO requirements,
  environment variable **names**, and separately gated capabilities.
- Unknown versions, unknown fields, incomplete graphs, unsupported proxy
  paths and undeclared secret names are rejected. The v2 preview never returns
  an approval ticket or uses the v1 installer/port allocator. It returns
  `staging_allowed: false` and `execution_allowed: false`; there is no
  v2 activation endpoint.
- An application already registered in UDA is reported as requiring
  reconciliation rather than silently replaced. Registered port conflicts are
  shown without mutating the registry.
- Source-authored entrypoints, build commands and literal environment values
  are not sent in the browser review plan. The only displayed environment
  information is required variable names. V2 manifests **must not** put
  credentials or secret values in Git under any circumstances.

This is a first reader/preview increment only: no systemd/Caddy changes,
database migrations, Compose execution, image builds, static publication
or service start/stop/restart. Real deployment remains blocked until
capability-specific adapters and disposable Ubuntu integration acceptance
are complete. The canonical v2 contract is currently a **draft**, not a
released UDA installer standard.

## Manifest example

```yaml
schema_version: 1
application:
  name: example-app
  display_name: Example App
  group: Development
source:
  branch: main
runtime:
  type: python
service:
  type: systemd
  entrypoint: ["python", "app.py"]
  port: auto
  health_path: /health
build:
  commands:
    - ["python", "-m", "compileall", "."]
proxy:
  enabled: true
  path: /apps/example-app/
  authentication: uda
deployment:
  auto_update: false
  rollback: true
  github_reporting: false
environment:
  required:
    - DATABASE_URL
    - SECRET_KEY
```

`environment.required` contains **only variable names**, never secret values.
Commands are argument vectors for review, not shell lines for immediate execution.

## Security properties

- Only HTTPS `github.com/owner/repository` URLs; no arbitrary hosts,
  embedded credentials, query strings or path prefixes.
- Only safe branch names. Exact source commit is recorded in the plan.
- The preview uses a short-lived `git clone --no-checkout` with the credential
  helper disabled; repository files and scripts are **not executed**.
- Python `yaml.safe_load` reads a size-limited manifest with known top-level
  sections. Malformed and unsafe fields are rejected.
- Port, service unit and app-name collisions are identified against the registry.
- The preview uses existing UDA dashboard authentication and CSRF protection.
- No registry write, systemd mutation, Caddy configuration edit, package install
  or GitHub publication occurs during preview.
- With a protected `UDA_GITHUB_TOKEN` present, UDA reads the branch head and
  then reads `uda.yaml` at that exact SHA using the read-only GitHub API. This
  also enables private repositories covered by the token's Contents: read access.
  Without a token, UDA uses a temporary no-checkout Git clone for public repos.
  Never insert tokens into repository URLs or manifests.
- A manifest **never grants permission to execute code**. Execution requires a
  separate trusted installer, administrator approval and sandboxing.

## Stage-only approval (implemented, not an installation)

The preview now allocates a candidate unprivileged port (default 5200–5999)
and issues a short-lived HMAC-signed ticket containing the exact SHA, commands,
service unit, environment variable names and proposed proxy path.

The administrator may click **Approve source staging only**. This:
- Requires existing dashboard Basic authentication and form CSRF validation.
- Rejects tampered/expired tickets (15-minute lifetime); a dashboard process
  restart invalidates outstanding tickets, safely requiring a new preview.
- Re-reads the repository and rejects source or plan changes.
- Rechecks application name, service-unit and port collisions.
- Uses the existing UDA deployment lock to avoid concurrent service changes.
- Clones a pinned commit to a separate staging directory and refuses symlinks.
- Stops without installing dependencies, running build commands, creating
  systemd units, changing the UDA registry or modifying Caddy.

An example configuration is `onboarding_staging_root` in the top-level
registry, defaulting to `~/.local/state/deployment-agent/onboarding-staging`.
This root should be an administrator-owned, private directory on a Linux
filesystem. Verify that the external USB filesystem is suitable before moving
this directory there.

**Private repository staging:** With a protected `UDA_GITHUB_TOKEN`, source is now
retrieved using GitHub's Git commit/tree/blob API at the exact reviewed SHA.
The transfer verifies each Git blob hash, rejects symlinks, submodules and
unexpected filesystem paths, and does not store the token in any Git remote.
This path is deliberately bounded to 1,000 files, 32 MiB total, and 8 MiB
per file. Oversized repositories require a separate approved retrieval method.
LFS-managed content and Git submodules are not automatically installed.
No generated plan is permission to execute repository-defined commands.

## Inactive release preparation (implemented)

`onboarding_release.py` can turn a verified staged checkout into a separate
commit-named directory under a designated release root. It excludes `.git`,
rejects symlinks and special files, limits repository size, records SHA-256
file hashes in `.uda-release.json`, and refuses to overwrite an existing
release. `verify_prepared_release` re-hashes the files and rejects modified
or additional files before later activation.

The module also generates a **preview-only** systemd service definition with
baseline restrictions (`NoNewPrivileges`, `PrivateTmp` and
`ProtectSystem`). It does **not** write this definition into systemd or
execute any application entrypoint. No registry, Caddy, service, database,
secrets or running application is changed.

A prepared directory is *commit-named and content-verified*, not inherently
tamper-proof or a completed build. A dedicated restricted worker, secure
ownership/permissions, dependency handling, artifact integrity and active
service verification are required before production use. No new web endpoint
can activate a release in this increment.

## Restricted build worker (implemented, not connected to production)

`onboarding_build.py` provides an explicitly approved, rootless Podman build
worker. It requires a builder image pinned by immutable SHA-256 digest, verifies
the prepared release receipt before starting, and uses `--network=none`,
`--read-only`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, CPU
and memory limits, and bounded process count. The approved source is mounted
read-only and the build output is a separate directory.

It rejects builds as root, missing Podman, and non-rootless configurations.
The worker is **not wired into the dashboard**, is not a production installer,
and cannot activate systemd, change Caddy or register an application. Offline
dependency/build caches or intentionally reviewed network egress policies are
needed for apps requiring downloads. Rootless isolation still requires
host-level AppArmor/seccomp and mount-policy acceptance.

## Activation preflight and rollback checklist (implemented, no execution)

The `onboarding_preflight.py` module checks the prepared release receipt and
SHA-256 file hashes, approved commit, reserved name/unit/port, service collisions,
protected environment file permissions and systemd unit preview. It returns an
audit checklist for staging, health checks, registry/Caddy publication and
rollback. **The result explicitly sets `execution_allowed: false`.**

No live systemd service, database, Caddy route or UDA application registration
is changed by this preflight. It does not yet provide a production installer,
perform network health checks, or establish runtime sandbox permissions.
The future worker must use dedicated least-privilege credentials, support
separate final approval and keep a previous known-good release for rollback.

## Disabled registry preview (implemented)

`onboarding_registry.py` produces a proposed registry record with
`enabled: false`, `auto_deploy: false`, `deployment_enabled: false`,
`proxy_enabled: false`, `show_on_home: false`, and
`github_reporting_enabled: false`. It compares the proposal with the
existing registry, rejects application/service/port collisions, and lists
compensating rollback actions for every later activation step. **It does not
write the registry**.

A future trusted activation worker must verify the current backup, use the
production lock, reserve a port, install the service, confirm loopback health,
apply protected UDA/Caddy configuration, verify login and record the actual
runtime SHA before enabling publication. Previous releases and configuration
must remain recoverable.

## Transaction controller (implemented, isolated from production)

`onboarding_transaction.py` defines an activation coordinator and a narrow
worker interface. It requires independent, trusted approval and enablement
flags, holds a deployment lock, captures a recovery snapshot, checks preflight,
then sequences systemd configuration, service start, health, disabled registry
publication, proxy refresh, UDA authentication, runtime SHA verification and
deployment attestation.

**Compensation is registered before every mutation**, allowing rollback even
when an operation partially completes before throwing an exception. The worker
must implement transaction-scoped snapshots, atomic changes and idempotent
compensating operations. Rollback failures are recorded and reported as
`rollback_failed`; they must never be reported as success. GitHub publication
is a separate post-commit step and its failure does not uninstall an otherwise
healthy application.

The controller has **no built-in privileged Ubuntu adapter**, is not called
by dashboard routes, and cannot change a live server by itself. The next
security-gated stage is implementing and independently accepting a restricted
systemd/Caddy/registry adapter with crash-recovery journaling.

## Durable activation audit (implemented, production integration pending)

`onboarding_journal.py` provides an append-only JSONL journal stored in a
private directory with file permissions `0600`. Each transition is flushed
and fsynced before proceeding; error strings are redacted to avoid leaking
application secrets into persistent audit files. Separate tests inject journal
write failures during rollback and verify that remaining compensations still
run.

The coordinator intentionally has no privileged systemd/Caddy adapter or
public activation route. The journal records the transaction state but does
not yet perform boot-time crash recovery. A trusted Ubuntu worker must scan
unresolved transactions on start-up, validate signed snapshots and resume or
reverse outstanding operations safely before enabling production activation.

## Local activation adapter (implemented as a controlled integration component)

`onboarding_adapter.py` implements the transaction interface using
transaction-scoped snapshots of the registry, systemd unit, generated proxy
configuration and deployed-SHA receipt. File changes are made with atomic
replace, and compensation restores the original file bytes. Unit and proxy
actions, health probes, SSO checks and runtime SHA verification are injected
callbacks. The corresponding tests run entirely in temporary directories and
inject failures at each activation stage.

The candidate registry record is enabled and its proxy route is published
**only after service health succeeds**. Authentication and live runtime-SHA
verification must subsequently pass before the deployment receipt is written.
Any failure requests reverse compensation. A failed compensation is reported
as `rollback_failed` and requires administrator recovery.

The adapter is **not wired to the dashboard or Ubuntu systemd** and no
production-capable callback implementation is provided in this increment.
Before deploying it, the implementation needs a dedicated service account,
strict path permissions, a non-bypassable approval handshake, durable snapshots,
restart-time reconciliation and real Caddy/systemd integration tests.

## Restart/crash recovery foundation (implemented)

`onboarding_recovery.py` now stores a durable transaction snapshot of the
original UDA registry, systemd unit, Caddy file and deployment receipt before
mutations. Snapshot storage is private (`0700` directory, `0600` files),
created with exclusive file creation and fsync. The activation journal records
`pending_undo` compensation intent **before** each side effect, allowing a
restart-time scanner to identify incomplete work.

`inspect_incomplete` performs **read-only** discovery of unfinished
transactions. `replay_compensations` can reverse the pending steps in order,
but only with a separate explicit approval and an adapter that holds the
deployment lock. Failed compensation is reported as `rollback_failed`, not a
successful recovery. The local adapter may optionally persist recovery
snapshots when `snapshot_root` is configured; unavailable/insecure storage
stops activation before changing the host.

**Still required:** A restricted Ubuntu worker that validates transaction
identity, operator approval, trusted path ownership and snapshot provenance,
and persists each recovery replay event. Crash recovery is not currently
auto-executed by UDA startup, and the dashboard has no activation route.
Large registry backups require an independently assessed retention policy.
These facilities must be validated in a disposable Ubuntu instance before
production use.

## Next increment: approved install engine

Build as a separate, auditable transaction:

1. Persist completed release approval/audit and separate *execution* permissions.
2. Resolve required environment values without passing secrets into the repository.
3. Reserve the proposed port under the deployment lock at final activation.
4. Support secure private source transfers pinned to the approved commit.
5. Use the prepared release verification receipt before restricted execution.
6. Execute approved build commands under a restricted service account/container.
6. Write an immutable release directory and carefully generated systemd unit.
7. Start the application on localhost and run a full health/permission check.
8. Atomically register it in UDA, then stage/reload Caddy and verify SSO.
9. Save the last healthy release and deployment attestation, and publish to
   GitHub only if reporting is expressly enabled and tests have passed.
10. On any failure restore the previous registry, proxy, release and service
    configuration, recording the complete audit trail.

No installer must run commands from an untrusted repo as the UDA admin/root
service. Private-repository manifest discovery is supported through a protected token;
private installation and node/static deployments still need separate acceptance
fixtures before they can be enabled.

## Validation

Run the following against the head SHA in an **independent disposable checkout**:

```shell
python3 -m pip install -r requirements.txt pytest
PYTHONPATH=. python3 -m pytest -q
```

Archive/restore PR #7 and reporting PR #8 remain stacked dependencies.
There is no live Ubuntu rollout until all three changes have passed
the acceptance and reconciliation checks.
