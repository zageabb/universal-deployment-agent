# Architecture and deployment lifecycle

The Universal Git Deployment Agent is a single Python process invoked periodically by a systemd user timer. One JSON registry describes every application the host is permitted to inspect or deploy.

It deliberately avoids a resident web service, inbound webhook, privileged daemon, or third-party Python dependency. GitHub access is outbound through each repository's configured Git remote.

## Components

| Component | Responsibility |
|---|---|
| `deploy_agent.py` | Validates the registry and performs checks or deployments |
| `config.json` | Host-local allowlist of applications and permitted commands |
| `deployment-agent.timer` | Starts a check every five minutes |
| `deployment-agent.service` | Runs one isolated check and exits |
| Application systemd services | Own application process lifecycle and restart behavior |
| Root launchers | Provide memorable manual restart commands that delegate to systemd |
| Rotating log | Records decisions, blocks, deployments, and rollback outcomes |

## Lifecycle

For each enabled application, the agent:

1. Resolves the configured repository path.
2. Confirms it is a Git repository on the configured branch.
3. Fetches that branch from `origin`.
4. Reads the local and remote commit identifiers.
5. Refuses automatic deployment when the working tree has tracked or untracked changes.
6. Reports the state without modification when `auto_deploy` is false.
7. Fast-forwards the clean checkout when an update is available.
8. Runs configured update commands in order.
9. Restarts the configured application service.
10. Polls the health endpoint until it succeeds or times out.
11. Restores the prior commit and restarts again if deployment validation fails.

A host-wide non-blocking file lock ensures only one agent run can operate at a time.

## State transitions

| Status | Meaning |
|---|---|
| `disabled` | The registry entry is present but not inspected |
| `monitored_dirty` | Changes exist; state is reported but files are untouched |
| `current` | Local and remote commits match |
| `update_available` | A new remote commit exists, but this run is dry or monitor-only |
| `deployed` | The update, restart, and health check succeeded |
| `blocked` | A safety check or command failed |

The deterministic JSON result is printed to standard output. Operational messages are written to the console, journal, and configured rotating log.

## Failure and rollback

The prior commit is captured before the fast-forward. If an update command, restart, or health check fails, rollback resets only the previously verified clean checkout to that commit. The application is restarted and health-checked again. The error remains visible even when rollback succeeds.

Rollback does not restore external schema or data migrations. Applications with irreversible migrations must supply backward-compatible migrations or disable automatic rollback.
