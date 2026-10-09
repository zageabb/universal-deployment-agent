# Development Status

Last reviewed: 2026-10-02
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

### DEV-005 — Automatic safe proxy migration monitor
Status: 🔨 IN PROGRESS
Priority: High
Owner/Agent: Codex
Branch: `main`
Depends on: DEV-003 migration contract
Can run in parallel with: individual application migrations
Integration status: implementation awaiting automated and live validation

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
- Tests and live validation: pending.
- User/business acceptance: pending.

Completion criteria:
- [x] Implementation exists.
- [x] Relevant files changed.
- [x] Tests added.
- [ ] Relevant tests pass.
- [ ] Dry-run correctly identifies current registry state.
- [ ] Timer installed and live execution validated.
- [ ] Commit evidence recorded and pushed to `main`.
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
