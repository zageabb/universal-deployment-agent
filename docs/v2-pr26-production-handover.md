# PR #26: production integration handover and evidence gates

**Status: HOLD — review-only instructions.** This document is a preparation
checklist, **not** a maintenance authorisation, deployment instruction, or
permission to merge PR #26 into `main`. The candidate integrated source
baseline was `fef8f222bf67a4a021c11929ccf42075c6260806`; compare the
actual PR head immediately before acceptance. Independent full regression
on this source was operator-reported **562 passed in 41.90s**.

## What is known

- The host is `m901-lenovo` and the production UDA files are installed in
  `/home/zageabb/.local/share/deployment-agent`; the installed application
  directory was **not** a Git checkout when the operator ran `git -C` there.
  **Do not** run `git reset`, `git pull`, or `git checkout` in that directory.
- The effective dashboard binding is `0.0.0.0:5030`. The operator explicitly
  requested **no binding change**. This document does not change firewall,
  transport security, Caddy or the unit.
- `deployment-agent.timer` and `uda-proxy-refresh.timer` were active on
  20 November 2026. The deployment-agent oneshot was failing on a DB
  Migration pre-deployment test. DB Migration PR #69 corrected the test policy
  mismatch and was merged at `8ec3e879d5070fc3564a762b8f7dd770586e8e5c`.
  The operator subsequently reported the scheduled deployment was verified.
  Retain the **actual latest journal and process exit code** as private
  evidence if a formal production acceptance is needed.
- PR #26 has new V1 operational dashboard and reporting paths as well as
  read-only V2 reviews. Archive/restore, service actions and the deployment
  poller can mutate live state. Existing V2 review/approval is **not**
  an activation ticket, and V2 signed revocation is still design-only.

## Installer completeness blocker discovered and corrected in review branch

The production unit invokes a **copied-file** runtime under
`~/.local/share/deployment-agent`, not a Git checkout. The original
`install.sh` copied `dashboard.py` and `deploy_agent.py` but did **not**
install the newly introduced `approval_*`, `onboarding_*`,
`deployment_reporting.py`, JSON schemas, new HTML templates or the
three V2 inventory helpers imported from `tools/`. This would risk
`ModuleNotFoundError` or missing-template failures after installing PR #26.

The review branch now includes the missing runtime modules and assets in
`install.sh` and a static install-manifest test in
`tests/test_runtime_install_manifest.py`. **This is a source fix,
not a live installation**, and does not repair or overwrite any installed
runtime. The original successful 562-case regression was on a prior
commit; rerun targeted install-manifest tests and the full suite against the
new final PR SHA before release acceptance.

The installer itself has operational side effects: recreates/updates its
virtual environment, writes installed files and user systemd units, runs
`daemon-reload` and enables/starts selected units. **Do not execute
`install.sh` merely to check its completeness**, and do not assume it is
an atomic installer/rollback procedure. Its existing unit enable/start
behaviour must be reviewed in the approved maintenance window,
especially any local unit drop-ins not included in the source template.
Preserve the exact dashboard `0.0.0.0:5030` binding as requested.

## Phase 1: read-only operator evidence collection (safe now)

Run as **zageabb** on the real host; no `sudo`, no use of the test account.
These print operational metadata, not registry credentials. Review outputs
before sharing: logs can still contain application names, paths or errors.

```bash
date -u
systemctl --user list-timers --all deployment-agent.timer uda-proxy-refresh.timer
systemctl --user show --no-pager \
  -p LoadState,ActiveState,SubState,UnitFileState,NextElapseUSecRealtime,Result \
  deployment-agent.timer uda-proxy-refresh.timer \
  deployment-agent.service uda-proxy-refresh.service
journalctl --user -u deployment-agent.service -n 35 --no-pager \
  | grep -Ei 'db-migration|failed|current|deployed|finished|success|rollback' || true
test -f /home/zageabb/.local/share/deployment-agent/deploy_agent.py \
  && echo 'installed UDA entrypoint present'
```

In a *separate, clean development checkout*, compare the PR head:

```bash
git fetch origin
git rev-parse origin/feature/uda-v2-process-crash-recovery
git status --porcelain
```

An empty `git status --porcelain` only proves that **that development
checkout** is clean. It does not prove the installed UDA files match the
candidate source. Obtain and document the actual installation source method
and installed-file revision from an approved installation record. Do not
paste `config.json`, environment files, access tokens, passwords or
protected SQLite files into GitHub comments.

## Phase 2: release approval required before any production mutation

Capture a named release owner and authorised maintenance operator, a
specific UTC window, the exact PR commit to be installed, the intended
installer/update mechanism, inventory of changed operational entrypoints,
and service health/SSO baseline. Explicitly record:

1. **Isolation:** preserve each timer's original enabled/active states; safely
   establish oneshot completion and lock ownership without deleting lock
   files. Stopping timers, modifying units or altering state requires
   approval and is deliberately **not** scripted here.
2. **Rollback:** a known-good **installed-file** snapshot matching the
   supported installation method, config and relevant owner/mode metadata;
   a separately verified restoration procedure and trigger conditions.
   A Git SHA by itself is insufficient for a non-Git installed tree.
3. **Data and registry safety:** an operator-owned backup procedure for
   protected config, registries, and any actual review-store SQLite database;
   validation of retention, file ownership and recovery access. Do not
   put copies into source trees or public issues.
4. **Boundaries:** no automatic V2 activation, database migration or
   privileged Docker harness on the host. Do not modify the current
   `0.0.0.0:5030` binding under this work item.
5. **Observability:** verify UDA timer results, application/SSO health,
   SheetBridge and Caddy routes before and after; identify a recovery
   operator who can restore original timer states on failure.

## Phase 3: release verdict

Use this table in the private change record, not as a synthetic PASS report.

| Gate | Evidence | Required verdict |
| --- | --- | --- |
| Source-integrated Python regression | 562 pass on candidate fef8f22; recheck head | PASS on exact reviewed head |
| DB Migration application blocker | PR #69 merged; operator verified follow-up | Host journal/exit evidence retained |
| Installation inventory | Determine actual installed copy/revision mechanism | Verified |
| Host baseline | Timers, service results, Caddy/SSO, app health | Verified |
| Named maintenance authority | UTC window, isolation, allowed writes, rollback owner | Explicitly approved |
| Restore rehearsed | Installed files, configuration and timer state | Demonstrated |
| Transport and reviewer custody | Document risk acceptance and permissions | Explicitly reviewed |
| V2 activation | No executor is being enabled | Explicitly prohibited |

**Release decision remains HOLD** while any gate is unverified. Do not
mark PR #26 ready or merge to `main` merely because unit tests passed or
because GitHub reports the branch is mergeable. The next controlled action
after approval is performed by the host operator using the authorised
install/rollback procedure, never by this document.
