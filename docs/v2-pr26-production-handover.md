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

## Disposable installed-runtime smoke (new acceptance gate)

The `tests/test_disposable_installed_runtime.py` suite creates a temporary
**non-Git** runtime from the explicit source references and fixed module list
in `install.sh`. It **does not execute `install.sh`** or invoke systemd,
Caddy, Docker, a deployed application, or any production environment.
A child Python process with isolated import search loads the copied
dashboard/agent, verifies the bundled V2 schema, renders the dashboard,
V1 onboarding and Approval Centre views using a synthetic private config,
and checks that an unauthorised Approval Centre POST fails closed.

From a clean, isolated UDA source test checkout, with its development
dependencies already installed:

```bash
sh -n install.sh
python -m pytest -q tests/test_runtime_install_manifest.py \
  tests/test_disposable_installed_runtime.py
python -m pytest -q
```

Record the **exact `git rev-parse HEAD`** and final pytest counts. The child
uses only a disposable config containing a fixed non-production test value.
It must not be pointed at the real UDA config or running service.
This tests module and template packaging but does **not** prove that a
production `install.sh` run will be atomic or preserve live systemd
unit drop-ins, or that live SSO/Caddy/health will survive a release.

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

## Read-only installed-file evidence command

Run from the **development checkout**, where the new helper exists, on
`m901-lenovo`. The command reads only a fixed list of installed runtime
source files, hashes those files, and stats the protected config without
opening or hashing the config. It does **not** inspect arbitrary files
in the runtime tree, run the installer, back up files, change permissions,
stop timers, or interact with Caddy/systemd:

```bash
cd ~/uda-integration-testing/uda-test
python3 tools/v2_release_evidence.py > /tmp/uda-v2-runtime-evidence.json
echo "inspection exit code: $?"
```

The report may return exit code 1 for review-required issues; it is not
proof of a broken active installation. In particular, the previously
observed installed runtime directory had mode `0775` and thus **may
produce `runtime_directory_writable_by_others`**. Inspect the directory's
ownership and group membership separately before recommending a change.
Do not auto-`chmod` on production as part of this phase.

File digests and status can be attached to a private change record after
checking its access controls. Do not attach protected config or SQLite
contents. Source-vs-installed hash differences are expected before an
upgrade; they are **not** rollback snapshots or proof of release success.

For isolated tests on the review branch, run:

```bash
python -m pytest -q tests/test_v2_release_evidence.py
python -m pytest -q
```

This helper explicitly reports `backup_verified=false`,
`rollback_verified=false`, and `production_upgrade_authorized=false`
under all circumstances. A successful inspection cannot grant any
release approval. An accountable operator must separately preserve a
known-good installed-file backup, configuration/registry backup, and
prove a supported restore path.

## Backup and disposable restore location: `/media/t/`

The operator proposed `/media/t/` as the location with more free storage.
Treat this as a **candidate mount**, not a confirmed secure backup location.
Create a dedicated directory under the mount **only after** verifying its
mount status, filesystem, available capacity, ownership and access-control
behaviour. Never silently fall back to writing below an unmounted
`/media/t` directory on the root filesystem.

Read-only preflight:

```bash
findmnt --target /media/t -o TARGET,SOURCE,FSTYPE,OPTIONS
df -hT /media/t
stat -c '%U %G %a %n' /media/t
findmnt --mountpoint /media/t -n -o TARGET
```

The **last command must identify `/media/t` as an actual mountpoint**.
If it doesn't, stop; do not create an archive there. Note that some
filesystems (for example exFAT or NTFS) cannot enforce Unix owner-only
permissions using normal `chmod` semantics. Where this is the case,
protected UDA configuration/registry backup requires authenticated
encryption with separately safeguarded keys, or an owner-private backup
destination on a Unix-permission-capable filesystem.

The proposed layout, **once preflight and access controls are accepted**, is:

```text
/media/t/uda-release/
  snapshots/          # protected, versioned, timestamped rollback archives
  restore-rehearsals/ # disposable extraction/restore checks, never live paths
  evidence/           # no secrets; hashes and signed release records only
```

A backup should include the installed **non-Git** UDA tree and the protected
configuration, relevant state/SQLite databases and actual user systemd units
and drop-ins. Confirm the source inventory first; `71M + 2.2M + 352K`
is a rough minimum, **not** proof that all state was captured. Consider
snapshot consistency if a live process is writing to a SQLite or JSON state
file. Do not copy live SQLite with `cp` as a claimed consistent snapshot;
use its backup API/appropriate operational method or a quiesced window.
Do not publish any archive, token, registry, SQLite backup or encryption key
in GitHub.

In the separately approved maintenance window, create the verified backup,
record file/manifest digests, extract into a **disposable** directory under
`restore-rehearsals/`, and validate file ownership/modes and application
imports without starting production units. Only afterwards decide whether
a real rollback procedure is demonstrated. **Neither this document nor
the previously reported 44 GB available on the root filesystem confirms
the capacity or protection of `/media/t/`.**

## Protected V1 snapshot and disposable restore tool — independent tests pending

A new operator-invoked tool, `tools/v2_snapshot_rehearsal.py`, is available
on the review branch. It has two explicit actions:

- `snapshot` writes a timestamped owner-private archive and SHA-256
  manifest inside `/media/t/uda-release/snapshots/`, after confirming the
  exact mountpoint is mounted, every workspace directory has mode 0700 and
  the caller owns it. It copies the installed non-Git runtime, full UDA
  configuration and state directories, and the user systemd directory
  (including current UDA overrides and symlinks). The nonempty
  `identity.db` is copied through SQLite's online backup API with
  `quick_check` on the copy. The empty `identity.sqlite3` is preserved
  as an empty file.
- `rehearse --snapshot-dir /media/t/uda-release/snapshots/uda-YYYYMMDDTHHMMSSZ`
  checks the archive hash, safely extracts **regular files/directories**
  into a disposable private directory under `restore-rehearsals/`, verifies
  critical installed config/override files and SQLite integrity, and removes
  the disposable directory. Archive symlink targets are **recorded as
  metadata and not recreated**. This is not proof of full systemd restore,
  environment-file loading or end-to-end live recovery.

**Run in the independent checkout first (no production snapshot):**

```bash
cd ~/uda-integration-testing/uda-test
git pull --ff-only
git rev-parse HEAD
python -m pytest -q tests/test_v2_snapshot_rehearsal.py
python -m pytest -q
```

**Only after tests pass, and after the snapshot scope/security has been
reviewed**, an authorised operator may create the owner-private
pre-upgrade snapshot, which writes **only** to `/media/t/uda-release/`
and reads the live source paths without restarting/stopping services:

```bash
python3 tools/v2_snapshot_rehearsal.py snapshot
```

The printed snapshot path can be passed to `rehearse --snapshot-dir`;
do not choose arbitrary tarballs or extract into production directories.
The source tree is never modified. No secrets, archives, identity database
copies or systemd override contents should be attached to GitHub.

**Consistency limitation:** although `identity.db` uses SQLite's online
backup API, copying other live files (config JSON, status JSON, other
application backup/state files) is not a filesystem-wide atomic snapshot.
Any other SQLite databases nested within the captured directories are not
individually processed. A fully consistent production rollback point
still requires separately approved maintenance/quiescence, an inventory
of writers and their state stores, and validation of the final archive.
The tool deliberately always reports `application_wide_consistency_verified:
false`. Do not declare the main release gate passed solely on this tool.

## Archived systemd symlink classification (read-only)

A separate helper, `tools/v2_symlink_rehearsal.py`, validates the
existing snapshot SHA-256 and inspects symbolic-link metadata within the
archive. It never extracts or recreates links, resolves targets on the
live host, enables a unit, or runs systemd. It classifies each link as
an internal regular-file/directory target, a link-to-link target, a
missing internal target, an outside-archive relative target, an
absolute target or an invalid target. External/absolute or missing
targets require **operator review**; not all are automatically defective,
since systemd can validly use external symlink targets.

From the isolated UDA source checkout, run the tests first:

```bash
python -m pytest -q tests/test_v2_symlink_rehearsal.py
python -m pytest -q
```

Only after these tests pass, inspect the **existing** verified snapshot
without modifying it:

```bash
python3 tools/v2_symlink_rehearsal.py \
  --snapshot-dir /media/t/uda-release/snapshots/uda-20261120T224219Z
```

The JSON output includes a count by classification and a filename-only
review list. The helper never prints symlink target values. Even a
`status: PASS` means the archive could be audited safely; it does **not**
mean systemd enablement or full rollback has been restored. A later
maintenance-window restoration must account for systemd units, drop-ins
and timer states, retaining the documented `0.0.0.0:5030` binding.

## Disposable UDA systemd enablement reconstruction (not activation)

`tools/v2_systemd_restore_rehearsal.py` validates the same protected
snapshot's SHA-256 and the **five UDA-specific** enablement links:
dashboard and home service links; deployment-agent, proxy refresh and proxy
migration timer links. For each it requires the corresponding archived
regular unit file plus the two dashboard/home `10-environment.conf`
override files. It rebuilds only these five links **inside a temporary
directory under `restore-rehearsals/`**, remapping acceptable archived
absolute user-systemd links to private relative targets. The temporary
directory is deleted after checks. No unrelated application links are
recreated, no unit is enabled/started, and no live user systemd configuration
is inspected or changed. The tool intentionally does **not** print
environment-file content.

Run independent regression on the new PR head:

```bash
cd ~/uda-integration-testing/uda-test
source .venv/bin/activate
git pull --ff-only
git rev-parse HEAD
python -m pytest -q tests/test_v2_systemd_restore_rehearsal.py
python -m pytest -q
```

Only after tests pass, inspect the existing verified archive:

```bash
python3 tools/v2_systemd_restore_rehearsal.py \
  --snapshot-dir /media/t/uda-release/snapshots/uda-20261120T224219Z
```

The expected report includes `uda_links_reconstructed=5`,
`environment_overrides_present=2`, and
`full_systemd_restore_rehearsed=false`. Any missing or unsafe link
is a **fail**, not permission to repair or modify the live host.
This provides file/link reconstruction evidence only: real systemd unit
loading, timer restoration, environment-file loading, application health,
lock isolation and rollback remain maintenance-window gates.

## Current release evidence (operator results)

The operator reported `PASS` from the real protected backup
`/media/t/uda-release/snapshots/uda-20261120T224219Z`:
snapshot creation; archive SHA-256; safe disposable extraction of
3,384 regular files; SQLite `quick_check=ok`; inventory of all
46 symlinks (43 absolute, two link-to-link, one internal regular,
no missing/invalid/outside-archive relative targets); seven critical
**live** UDA link targets present; and disposable reconstruction of
five UDA user-systemd enablement links against five backed-up unit
files plus two override files. All link restoration remained within
the temporary private backup tree, with `systemctl_invoked=false`.

**These are distinct checks, not a full operational rollback:** the
online backup covers `identity.db`, but the entire running state is
not atomically frozen; no restored unit has actually been loaded,
enabled or started; Caddy/SSO and app health have not been rechecked
after a restore; and no production rollback or upgrade was authorised.

## Fresh host baseline (read-only, approval still required)

New `tools/v2_host_release_baseline.py` reads only the allowlisted
user systemd timer/service properties through `systemctl --user show`:
`LoadState`, `ActiveState`, `SubState`, `UnitFileState`,
`Result`, `ExecMainStatus`, and `NextElapseUSecRealtime`.
It does not read credentials or environment override values and does not
invoke `start`, `stop`, `enable`, `disable`, `daemon-reload`,
or the UDA installer. All observations are snapshots in time, not
a guarantee that the host remains in that state.

Validate **in the isolated test checkout** before running it:

```bash
cd ~/uda-integration-testing/uda-test
source .venv/bin/activate
git pull --ff-only
git rev-parse HEAD
python -m pytest -q tests/test_v2_host_release_baseline.py
python -m pytest -q
```

If the tests pass, the **read-only** host inspection is:

```bash
python3 tools/v2_host_release_baseline.py
```

An exit code of 1 means one or more systemd unit observations were
unavailable/incomplete; investigate, do not reset units automatically.
Even an exit code of zero is not a green production release verdict.
This helper deliberately reports
`caddy_health_verified=false`, `sso_health_verified=false`,
`application_health_verified=false`,
`installed_runtime_rollback_verified=false` and
`production_upgrade_authorized=false`. Caddy reverse-proxy routes,
dashboard login/SSO, application liveness, original timer state,
operator-approved quiescence and rollback triggers require separate
explicit evidence. Avoid publishing unit environment data or private
snapshot files in public issue comments.

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
