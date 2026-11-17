# UDA-DEPLOY-002 — Repository-based onboarding

Development stage: **read-only preview implemented; installation not yet enabled**.

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
- Public repositories are supported first. Private repository onboarding requires
  a future restricted GitHub credential mechanism; do not insert access tokens
  into repository URLs or manifests.
- A manifest **never grants permission to execute code**. Execution requires a
  separate trusted installer, administrator approval and sandboxing.

## Next increment: approved install engine

Build as a separate, auditable transaction:

1. Persist a signed or expiring installation plan, pinned to the exact commit SHA.
2. Require administrator approval and resolve required environment names.
3. Allocate an available host port and service unit under a managed namespace.
4. Clone the exact commit to a staging directory outside the production tree.
5. Execute approved build commands under a restricted service account/container.
6. Write an immutable release directory and carefully generated systemd unit.
7. Start the application on localhost and run a full health/permission check.
8. Atomically register it in UDA, then stage/reload Caddy and verify SSO.
9. Save the last healthy release and deployment attestation, and publish to
   GitHub only if reporting is expressly enabled and tests have passed.
10. On any failure restore the previous registry, proxy, release and service
    configuration, recording the complete audit trail.

No installer must run commands from an untrusted repo as the UDA admin/root
service. Private repositories and node/static deployments need separate test
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
