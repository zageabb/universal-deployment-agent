# Operations and recovery

## Common commands

Run immediately:

```bash
~/ollama-chat/deployment_agent_start
```

Run without changing applications:

```bash
~/.local/share/deployment-agent/deploy_agent.py \
  --config ~/.config/deployment-agent/config.json \
  --dry-run
```

Inspect scheduling and the most recent run:

```bash
systemctl --user list-timers deployment-agent.timer
systemctl --user status deployment-agent.service
```

Follow logs:

```bash
journalctl --user -u deployment-agent.service -f
tail -f ~/.local/state/deployment-agent/deploy.log
```

Restart a registered application manually:

```bash
~/ollama-chat/price_estimator_start
```

## Responding to statuses

### `monitored_dirty`

Run `git status --short` in that application. Determine whether the files are source changes to publish or runtime state to relocate. Preserve changes before cleaning the checkout. Never enable automatic deployment merely by hiding meaningful tracked changes.

### `blocked`

Read the JSON `error`, rotating log, and systemd journal. Common causes are:

- wrong branch
- missing repository
- dirty checkout with automatic deployment enabled
- GitHub authentication or network failure
- dependency installation failure
- restart failure
- health timeout

### Health-check failure

Inspect both the application service and deployment service:

```bash
systemctl --user status my-app.service
journalctl --user -u my-app.service -n 100
journalctl --user -u deployment-agent.service -n 100
```

The agent attempts rollback automatically. Confirm the repository commit and health state before re-enabling deployment.

## Temporarily pausing deployment

Pause all checks:

```bash
systemctl --user disable --now deployment-agent.timer
```

Pause one application by setting `auto_deploy` to false. Set `enabled` to false only when the application should not even be fetched or reported.

## Manual recovery

1. Disable the timer.
2. Inspect the repository, service journal, application log, and health endpoint.
3. Restore application data from its own backup system if required.
4. Select and verify the intended Git commit.
5. Restart the application service.
6. Run the agent in dry mode.
7. Re-enable the timer only when the checkout is clean and health is stable.

The agent does not back up databases or user uploads. Those require application-specific backup and restore procedures.

## Updating the deployment agent

```bash
cd ~/ollama-chat/universal-deployment-agent
git pull --ff-only
./install.sh
systemctl --user daemon-reload
```

Review registry examples before replacing the host-local registry; `install.sh` intentionally leaves it untouched.
