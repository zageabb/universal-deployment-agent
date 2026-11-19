# UDA V2-003 — main-branch integration readiness

**Date:** 19 November 2026  
**Scope:** [PR #26](https://github.com/zageabb/universal-deployment-agent/pull/26)
from `feature/uda-v2-process-crash-recovery` to `main`.

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
