# Installation

## Requirements

- Linux with systemd user services
- Python 3.10 or newer
- Git
- outbound GitHub access
- a local Unix user that owns the application checkouts
- application health endpoints or stable HTTP pages

The agent itself requires only the Python standard library.

## Install the agent

```bash
git clone https://github.com/zageabb/universal-deployment-agent.git
cd universal-deployment-agent
./install.sh
```

The installer creates:

```text
~/.local/share/deployment-agent/deploy_agent.py
~/.config/deployment-agent/config.json
~/.config/systemd/user/deployment-agent.service
~/.config/systemd/user/deployment-agent.timer
```

An existing registry is never overwritten by `install.sh`.

## Configure applications

Edit `~/.config/deployment-agent/config.json`. Begin with every application in monitor-only mode:

```json
{
  "name": "my-app",
  "enabled": true,
  "auto_deploy": false,
  "repo_path": "/home/example/apps/my-app",
  "branch": "main",
  "restart_command": ["systemctl", "--user", "restart", "my-app.service"],
  "health_url": "http://127.0.0.1:5055/health"
}
```

## Validate before enabling

```bash
~/.local/share/deployment-agent/deploy_agent.py \
  --config ~/.config/deployment-agent/config.json \
  --dry-run
```

Resolve every unexpected `blocked` or `monitored_dirty` result. Do not remove application data merely to make a checkout clean; relocate it to a persistent directory first.

## Enable recurring checks

```bash
systemctl --user daemon-reload
systemctl --user enable --now deployment-agent.timer
loginctl enable-linger "$USER"
```

Linger allows the user service manager and timer to continue after logout. Depending on host policy, enabling it may require administrator approval.

Verify scheduling:

```bash
systemctl --user list-timers deployment-agent.timer
systemctl --user status deployment-agent.timer
```

## Repository authentication

Public repositories need no credentials. For a private repository, use a repository-scoped, read-only GitHub deploy key. Confirm unattended access before enabling automatic deployment:

```bash
git -C /path/to/application fetch origin main
```

Do not store GitHub tokens, private keys, passwords, or application secrets in the deployment registry.
