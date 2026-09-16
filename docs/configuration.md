# Registry reference and onboarding

The registry is JSON. Its top level contains host-wide paths and an `applications` array.

## Top-level fields

| Field | Required | Description |
|---|---:|---|
| `applications` | Yes | Application allowlist |
| `lock_file` | No | Cross-process lock; defaults to `/tmp/deployment-agent.lock` |
| `log_file` | No | Rotating operational log |

## Application fields

| Field | Required | Description |
|---|---:|---|
| `name` | Yes | Unique log and result identifier |
| `enabled` | No | Whether to inspect the application; defaults to false |
| `auto_deploy` | No | Whether clean updates may be applied; defaults to false |
| `deployment_enabled` | No | Set false for service-only legacy apps that should skip all Git inspection and deployment |
| `repo_path` | Yes | Absolute or home-relative Git checkout path |
| `branch` | Yes | Local and `origin` branch to follow |
| `restart_command` | Yes | Argument array used after update or rollback |
| `health_url` | Yes | HTTP endpoint that must return a successful response |
| `app_url` | No | Front-end URL for the home-page card; takes precedence over the health URL |
| `display_name` | No | Friendly application title on the home page |
| `show_on_home` | No | Set false to omit a service from the home page; libraries are always omitted |
| `service_unit` | No | Valid systemd user `.service` unit exposed to authenticated dashboard start/stop/restart controls |
| `update_commands` | No | Ordered argument arrays executed in the repository |
| `rollback` | No | Restore the prior commit after failure; defaults to true |
| `git_timeout` | No | Fetch timeout in seconds; defaults to 120 |
| `command_timeout` | No | Per-update-command timeout; defaults to 300 |
| `restart_timeout` | No | Restart-command timeout; defaults to 60 |
| `health_timeout` | No | Total health polling window; defaults to 30 |
| `environment_file` | No | Default protected environment file inherited by scheduled jobs |
| `scheduled_jobs` | No | Declarative scheduled oneshot jobs; defaults to an empty list |

Commands are arrays rather than shell strings. Shell expansion, pipes, redirects, command substitution, and implicit environment interpolation are not performed.

See [Scheduled application jobs](scheduled-jobs.md) for the job schema,
supported schedule types, lifecycle, and LedgerOne example.

When `service_unit` is configured, the authenticated dashboard may run only `systemctl --user start`, `stop`, or `restart` for that exact validated unit. It does not accept arbitrary service names or commands from requests. Mutating dashboard requests also require the form token provided by the authenticated dashboard. Refresh the page after restarting the dashboard to obtain a new token. Service actions use the deployment lock and return HTTP 409 while a deployment or another service action is running.

## Onboarding checklist

1. Ensure the application has a dedicated Git repository and deployment branch.
2. Move databases, uploads, logs, prompts edited at runtime, generated assets, and `.env` files outside the checkout or add appropriate ignore rules.
3. Confirm `git status --porcelain` is empty.
4. Create a systemd user service with a stable working directory and environment file.
5. Add a reliable health endpoint that checks application readiness without changing state.
6. Add the application with `enabled: true` and `auto_deploy: false`.
7. Run a dry check and inspect the reported commits.
8. Test the restart command manually.
9. Test the health URL locally on the server.
10. Set `auto_deploy: true` and run one real-mode check.

## Update commands

Only add deterministic, non-interactive commands. For example:

```json
"update_commands": [
  ["/home/example/venv/bin/pip", "install", "-r", "requirements.txt"],
  ["/home/example/venv/bin/python", "manage.py", "migrate"]
]
```

Commands run after the Git fast-forward and before restart. A failure triggers rollback when enabled.

## Monitor-only mode

Use monitor-only mode for legacy or locally modified applications:

```json
"enabled": true,
"auto_deploy": false
```

The agent still fetches GitHub and reports whether an update exists. It never changes files or restarts that application.

## Python Git dependencies and libraries

Set `python` to the absolute path of the application's dedicated virtualenv
interpreter. The agent runs `python -m pip install --upgrade --force-reinstall -r requirements.txt` on every
application revision change, before `update_commands`. `requirements` can override
the filename. Remove the equivalent pip command from `update_commands`; retain
migrations and other setup commands in their existing order. The requirements file
is authoritative: pinned Git revisions are installed by pip, including when the
package version itself has not changed. There is no shared Research Core checkout,
PYTHONPATH override, submodule, or automatic consumer update on library pushes.

Each consumer must use a separate virtualenv. Do not point multiple applications
at the same environment when they may pin different library revisions. Git,
Python's venv support, pip, and outbound HTTPS to GitHub and the package index are
required. Public Git dependencies do not require a PAT.

A failed update restores the previous source when rollback is enabled. For entries
with `python`, it also reinstalls the previous requirements before any recovery
restart. Failures before restart leave the existing process running. If restoring
dependencies fails, no recovery restart occurs and both errors are reported.
In-place pip installation is not transactional; the running process may still be
affected by partially changed dependencies. This does not roll back databases or
remove extra packages introduced by a failed update. Existing virtualenvs are never
deleted. Legacy command-only entries cannot restore dependency state automatically.

Successful deployments report interpreter/environment, installed Research Core
version and PEP 610 Git commit, service state, TCP port reachability, and health
result. Diagnostic collection errors do not roll back a healthy deployment.

For a library use `kind: "library"` and explicit `update_commands` that install and
test it in its own environment. `restart_command` and `health_url` are unnecessary;
no service is started and no port is allocated. For example:

```json
{
  "name": "research-core",
  "kind": "library",
  "enabled": true,
  "auto_deploy": true,
  "repo_path": "/home/example/research-core",
  "branch": "main",
  "update_commands": [
    ["/home/example/research-core/.venv/bin/python", "-m", "pip", "install", ".", "pytest"],
    ["/home/example/research-core/.venv/bin/python", "-m", "pytest", "-q"]
  ]
}
```

Create this library checkout and environment once before registration. Keep it
outside consumer source directories. Library validation failure restores source;
its validation environment is disposable and is reinstalled on the next attempt.

Ubuntu pip 22.0.2 retained the old same-version Git package even with `--upgrade`
in an integration test. `--force-reinstall` ensures the selected revision is
actually installed. This reinstalls the requirements set on each application
update and may select newer versions within unpinned constraints; use pinned
requirements where reproducibility is required.

`examples/ollama-chat/research-core-consumers.json` shows the three consumer
entries. Merge entries into the existing registry; do not replace unrelated
applications or credentials. Existing shared-environment services need a one-time
interpreter and PATH change to their app's `.venv` after dependencies are installed
and checked. Preserve all startup arguments, working directories, environment
files, ports, and timers, including Internet Pricing's ingestion service.

Run `python3 -m pytest -q` from the repository root. The optional real-pip test
`python3 tests/check_git_pin.py` creates temporary local Git commits with the same
package version, tests SHA A → B → A in a disposable virtualenv, and requires
package-index access for wheel. It does not modify application repositories.

## Service-only mode

Legacy applications without a Git checkout can still use dashboard health and service controls:

```json
"enabled": true,
"deployment_enabled": false,
"auto_deploy": false
```

The recurring agent records `service_only` and performs no Git operations for that application.
