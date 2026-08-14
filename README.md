# Universal Git Deployment Agent

A small, dependency-free deployment poller for multiple applications on one Linux host. It checks configured Git branches, fast-forwards clean repositories, runs allowlisted update commands, restarts the corresponding systemd user service, verifies its health endpoint, and rolls back a failed deployment.

The Flask dashboard shows agent version and last-run status, application health, commits and deployment results. Authorized applications can be checked and updated immediately from their card. It listens on port 5030 and requires HTTP Basic authentication: username `admin`, password from `dashboard_token` in the local configuration. Open `http://SERVER:5030` from the trusted network.

## Documentation

- [Architecture and deployment lifecycle](docs/architecture.md)
- [Installation and initial configuration](docs/installation.md)
- [Registry reference and application onboarding](docs/configuration.md)
- [Operations, monitoring, and recovery](docs/operations.md)
- [Security model](docs/security.md)
- [Ollama Chat reference deployment](docs/ollama-chat.md)

## Safety model

- Applications are disabled unless explicitly enabled.
- Enabled applications default to monitor-only until `auto_deploy` is explicitly set to `true`.
- Dirty working trees are never modified.
- Updates must be fast-forwardable from the configured remote branch.
- Only argument-array commands stored in the local registry can run.
- A host-wide lock prevents concurrent deployments.
- Failed restarts or health checks restore the previous commit.
- Rotating logs preserve deployment outcomes without growing indefinitely.

Operational data, environment files, logs, uploads, databases, and server-specific configuration should live outside Git checkouts.

## Install

```bash
./install.sh
```

Edit `~/.config/deployment-agent/config.json`, then validate without making changes:

```bash
~/.local/share/deployment-agent/deploy_agent.py \
  --config ~/.config/deployment-agent/config.json \
  --dry-run
```

Enable the recurring check only after the dry run is clean:

```bash
systemctl --user enable --now deployment-agent.timer
systemctl --user list-timers deployment-agent.timer
```

Review activity with:

```bash
journalctl --user -u deployment-agent.service
tail -f ~/.local/state/deployment-agent/deploy.log
```

For a production installation, follow the complete [installation guide](docs/installation.md), including user-service persistence and a dry-run audit.

## Registry

See `config.example.json`. Each application defines its repository path, deployment branch, optional update commands, systemd restart command, health endpoint, timeouts, and rollback policy.

Use `"enabled": true, "auto_deploy": false` while preparing an existing checkout. The agent will fetch and report its state but will not change files or restart it. Change `auto_deploy` to `true` only after the working tree is clean and operational data has been moved outside the repository.

For private repositories, install a repository-scoped read-only GitHub deploy key. Do not place tokens in the registry.

## Ollama-chat example

`examples/ollama-chat` contains the reference registry, user services, and canonical root launchers for the six applications on the Ubuntu host. The launchers live in `~/ollama-chat` and delegate process lifecycle to systemd, preventing duplicate background processes.

The reference registry enables automatic deployment only for clean, prepared checkouts. Applications containing locally edited prompts or runtime files remain monitor-only until that state is moved outside Git.
