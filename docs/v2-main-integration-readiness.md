# UDA V2-003 — main-branch integration readiness

**Date:** 19 November 2026  
**Scope:** [PR #26](https://github.com/zageabb/universal-deployment-agent/pull/26)
from `feature/uda-v2-process-crash-recovery` to `main`.

**Release handover:** See [PR #26 production evidence and rollback checklist](v2-pr26-production-handover.md), including the important distinction between the installed non-Git UDA files and the separate source checkout. This is a read-only preparation record, not approval to merge or deploy.

## Decision

**Feature-stack integration: ACCEPTED.** PR #9 and PRs #12–#25 are merged
into their declared intermediate feature-base branches. The final #25 merge
commit was confirmed to have the identical Git tree to the passing
pre-merge head.

**Main-branch merge: HOLD for operational scope review.** PR #26
contains earlier v1 onboarding/deployment reporting code as well as V2
simulation and disposable acceptance. Before allowing the production
deployment-agent timer to update its checkout, review the combined
existing dashboard mutations, deployment-agent/reporting hooks and proxy
refresh paths. Passing v2 unit tests alone does not approve this release
for a live unattended deployment.

## Verified GitHub acceptance

- Full UDA regression on PR #26: **478 tests passed** on both Python 3.12
  and 3.13 ([run 44563541614](https://github.com/zageabb/universal-deployment-agent/actions/runs/44563541614)).
- Independent V2 full-stack integration regression: **478 passed** on each
  Python version ([run 44563541579](https://github.com/zageabb/universal-deployment-agent/actions/runs/44563541579)).
- Proxy migration: **5 passed** ([run 44563541562](https://github.com/zageabb/universal-deployment-agent/actions/runs/44563541562)).
- The earlier real systemd lifecycle and SIGKILL recovery tests passed in
  GitHub-hosted disposable Ubuntu 22.04 and 24.04 containers.
- `tests/test_v2_main_integration_guard.py` enforces that the normal
  dashboard exposes a V2 **preview** but does not import the V2 sandbox
  deployment/recovery worker, that V2 compensation is review-only, and
  that the disposable integration harness is restricted to GitHub-hosted
  CI with `--network none` and no host mounts.

## Explicitly separate v1 from V2

Existing UDA v1 dashboard routes **can** already invoke `deploy_agent.py`,
run `systemctl --user` service actions, enable/disable services and request
a Caddy proxy refresh. Those paths are intentionally **not** claimed to be
non-mutating. The reviewed V2 path is preview/rehearsal only and has no
installer authorization or automatic recovery permission.

The `onboarding_worker_policy.worker_capabilities` output explicitly
denies `production_activation` and `automatic_crash_recovery`, regardless
of manifest/dashboard options. Review-only tokens are not worker execution
credentials.

## Live host acceptance (not yet done)

`m901-lenovo` uses Ubuntu 22.04.5 with systemd 249; it runs
`deployment-agent.timer` about every five minutes, and
`uda-proxy-refresh.timer` about every two minutes. The former has a
recurring `db-migration` failed regression and may hold the shared
deployment lock for approximately 30 seconds.

Before a live integration/upgrade:

1. Approve a maintenance window and record the original status/next-run
   times of both timers and all relevant SheetBridge/SSO/health checks.
2. Stop and verify the deployment-agent timer and current oneshot/lock holder
   have fully exited; also isolate proxy refresh when proxy config is tested.
3. Use a pinned Git SHA, isolated test checkout/config/locks/unit names and
   dedicated loopback ports. Never use the CI-only privileged Docker harness
   against the production Docker daemon.
4. Test failures, health, rollback and authorization without touching
   SheetBridge or existing Caddy routes.
5. Restore recorded timer state, verify expected next-run times, confirm
   services/SSO/Caddy health and ensure no test artifacts remain.

This document does **not** authorize those state-changing maintenance
operations. Live host testing and main merge require independent approval.

## Additional zero-mutation host inspection gate

`python3 onboarding_v2_host_readiness.py` provides an optional read-only
observation of the **local user-systemd** deployment and proxy-refresh timers
and their paired oneshot services, including the currently reported next run.
It accepts Ubuntu 22.04 and 24.04 and returns fail-closed blockers when either
timer is active, a oneshot is running, the OS is unsupported, or an observation
fails. It does **not** issue `stop`, `disable`, `start`, `systemctl reload`,
lock operations or deploy commands, and never displays secrets from the UDA
configuration. The command may exit with code 1 when timers are running;
that is the **expected pre-maintenance status**, not a reason to disable the
timers without an agreed maintenance window.

A result marked `ready_for_isolated_test_scheduling` only records that the
limited four systemd status checks showed no blockers. It explicitly says
`deployment_allowed=false`, `timer_mutation_allowed=false` and
`lock_holder_verified=false`. Independent deployment-lock checks, pinned
repositories, reserved loopback ports, signed execution approval and planned
timer restoration remain mandatory before any host-local tests.

`tests/test_onboarding_v2_host_readiness.py` checks both OS versions,
active timers, active service, failed status inspection, arbitrary unit names,
oversized output and nonauthorization. All tests inject fake systemctl output.

## Additional fail-closed systemd validation

The host readiness inspector now rejects unloaded/missing systemd units, failed units (including failed oneshot services), and incomplete `systemctl show` responses, even when the timers are inactive. Three isolated mocked regressions cover those cases. This is **not** maintenance authorization. No production timer state or live host configuration was changed. The added tests must pass in the PR #26 full regression before the integration can be considered for review.


## V1 operational-path review — 19 November 2026

The existing dashboard uses HTTP Basic authentication backed by a configured token
and checks an application-generated CSRF token on every POST. These controls are
mandatory for all of the following **state-changing** operations and must not
be bypassed by V2 preview routes:

| Route / operation | Host effects | Required pre-merge acceptance |
| --- | --- | --- |
| POST `/applications/<name>/update` | Spawn deployment poller, Git fast-forward, dependency install, restart and health check | Enforce enabled/auto_deploy/deployment_enabled, shared lock in poller, failure and rollback checks |
| POST `/applications/<name>/service/<action>` | Start/stop/restart selected user service | Action allowlist, configured unit name, authorization, non-blocking deployment lock |
| POST `/applications/<name>/enabled` | Enable/disable user unit, registry write, scheduled job reconciliation, optional Caddy refresh | Lock, valid service_unit, failed subprocess protection, document partial-commit recovery |
| POST `/applications/<name>/scheduled-jobs/<job_name>/run` | Start generated user service | Enabled registry/job, generated unit names, deployment lock |
| POST `/onboarding/stage` | Stage vetted repository snapshot in local staging directory | Signed approval ticket, deployment lock, no activation/systemd/proxy mutation |
| POST group/assignment routes | Mutate JSON registry and grouping | Auth, CSRF, validated atomic registry replacement |

**Known v1 operational caveat:** archive/restore is a multi-step operation,
not an atomic transaction across systemd, registry, scheduled jobs and proxy
refresh. If scheduled job reconciliation or Caddy refresh fails after the
registry changes, the dashboard reports a partial failure; an operator must
verify each resulting state and reconcile under a controlled maintenance
window. It is incorrect to assume that rollback has occurred.

**V1 regression hardening:** PR #26 now catches manual update executable/timeout
failure and reports it through the dashboard rather than generating a 500.
Proxy-refresh executable/timeout failure after archive/restore is reported as
a partial state needing operator attention, not as an unhandled exception.
Three regressions exercise these scenarios with mocked subprocesses.

## Live-host maintenance isolation checklist (approval required)

All commands below are *instructions for an operator during a separately
approved window*, **not** actions authorized for an automated agent or this PR.
Do not paste the state-changing commands into a CI job or the production
Docker acceptance harness. Run commands as the same user whose systemd user
manager owns UDA. Always retain the recorded unit states.

### A. Read-only baseline, before requesting a window

```bash
python3 onboarding_v2_host_readiness.py
systemctl --user list-timers --all deployment-agent.timer uda-proxy-refresh.timer
systemctl --user show deployment-agent.timer uda-proxy-refresh.timer deployment-agent.service uda-proxy-refresh.service --property=LoadState,ActiveState,SubState,UnitFileState,NextElapseUSecRealtime
systemctl --user status deployment-agent.service uda-proxy-refresh.service --no-pager
git rev-parse HEAD
git status --porcelain
```

Record all expected application health endpoints, SSO tests, SheetBridge
service state and Caddy configuration checks with an accountable operator.
The host-readiness script is advisory and must never be interpreted as
authorization. An active timer is an expected blocker before isolation.

### B. Isolate only in the approved window

Record whether each timer was enabled and active **individually**. After
approval, the operator can stop the timers, but must not assume that stopping
a timer stops a service already in progress. Check whether the corresponding
oneshot is still active, confirm the production deployment lock is released
and identify/resolve a legitimate lock holder before proceeding. Never
remove or truncate the lock file to force access. Verify the proxy-refresh
service is quiescent and preserve existing Caddy routes. No test may use
the production config, checkout, lock path, port or systemd unit names.

### C. Disconnected acceptance

Use a separate pinned-SHA checkout and explicit isolated config, state
directory, lock path, unit names and loopback ports. Execute read-only
preflight, mocked regression and health validation first. Any subsequent
state-changing disposable or host-local test requires its **own** approval
and a documented rollback procedure; no automatic activation or
compensation replay is permitted. Never run privileged Docker with host
mounts or production Docker access in this validation.

### D. Restore and verify

Restore **exactly** each original timer's active/enabled state rather than
blindly enabling both. Confirm no lingering test processes, systemd units,
listeners or changed proxy config, then compare Git commit, deployment state,
SSO, SheetBridge, Caddy routes and health endpoints to baseline. Record any
drift and stop the release if restoration is incomplete.

**Outstanding approvals:** accountable production owner must approve the
maintenance window, isolation/recovery operator, scope of allowed writes and
rollback plan. A documented read-only preflight and green CI alone do not
satisfy those approvals. Keep PR #26 in draft until sign-off and host evidence
are attached.


## Additional read-only host-inspection fail-closed tests — 24 November 2026

The host-readiness inspector now rejects ambiguous `systemctl show` evidence:
duplicate known properties are treated as inspection errors, and any timer
or oneshot state other than fully `inactive` is a scheduling blocker.
Known `failed` states remain blocked by `systemd_unit_failed`.
This protects against inadvertently reporting readiness while a timer or
oneshot is activating, deactivating, reloading or returning an unfamiliar state.

The added mocked tests cover four transitional/unrecognised timer states,
two unexpected oneshot states and duplicate `ActiveState` properties.
No production services, timers, Caddy configuration or locks are modified.
These checks grant no maintenance, merge or V2 activation authorisation.
