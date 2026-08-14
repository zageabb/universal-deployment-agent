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
| `repo_path` | Yes | Absolute or home-relative Git checkout path |
| `branch` | Yes | Local and `origin` branch to follow |
| `restart_command` | Yes | Argument array used after update or rollback |
| `health_url` | Yes | HTTP endpoint that must return a successful response |
| `update_commands` | No | Ordered argument arrays executed in the repository |
| `rollback` | No | Restore the prior commit after failure; defaults to true |
| `git_timeout` | No | Fetch timeout in seconds; defaults to 120 |
| `command_timeout` | No | Per-update-command timeout; defaults to 300 |
| `restart_timeout` | No | Restart-command timeout; defaults to 60 |
| `health_timeout` | No | Total health polling window; defaults to 30 |

Commands are arrays rather than shell strings. Shell expansion, pipes, redirects, command substitution, and implicit environment interpolation are not performed.

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
