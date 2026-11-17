# UDA-DEPLOY-002 — Repository-based onboarding

Development stage: **read-only preview plus explicit, signed, stage-only approval implemented; installation not yet enabled**.

## Purpose

An administrator opens **UDA → Install from GitHub**, supplies an HTTPS GitHub
repository URL and branch, and receives a plan derived from the repository's
root `uda.yaml` manifest. This removes the manual inspection step from
ChatGPT Desktop. UDA does not yet apply the installation plan.

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

**Current limitation:** Stage-only Git cloning uses public HTTPS access. Private
repository manifest previews are supported through the read-only GitHub API,
but private source checkout requires a separately secured transfer mechanism.
A private repo may therefore preview successfully but cannot yet be staged.
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
