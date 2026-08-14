# Universal Git Deployment Agent

A small, dependency-free deployment poller for multiple applications on one Linux host. It checks configured Git branches, fast-forwards clean repositories, runs allowlisted update commands, restarts the corresponding systemd user service, verifies its health endpoint, and rolls back a failed deployment.

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

## Registry

See `config.example.json`. Each application defines its repository path, deployment branch, optional update commands, systemd restart command, health endpoint, timeouts, and rollback policy.

Use `"enabled": true, "auto_deploy": false` while preparing an existing checkout. The agent will fetch and report its state but will not change files or restart it. Change `auto_deploy` to `true` only after the working tree is clean and operational data has been moved outside the repository.

For private repositories, install a repository-scoped read-only GitHub deploy key. Do not place tokens in the registry.

## Ollama-chat example

`examples/ollama-chat` contains the monitor-only registry, user services, and canonical root launchers for the six applications on the reference Ubuntu host. The launchers live in `~/ollama-chat` and delegate process lifecycle to systemd, preventing duplicate background processes.

The reference registry enables automatic deployment only for clean, prepared checkouts. Applications containing locally edited prompts or runtime files remain monitor-only until that state is moved outside Git.
