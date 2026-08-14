# Security model

The deployment agent is intentionally narrow. It reads one local allowlist, performs Git operations in listed repositories, executes listed argument-array commands, restarts listed services, and requests listed health URLs.

## Trust boundaries

- The host administrator controls the registry.
- GitHub maintainers control code merged into configured deployment branches.
- Application repositories and their dependency manifests are trusted deployment inputs.
- Health responses are used only as success signals, not executed or interpreted as instructions.

## Controls

- No inbound network listener
- No webhook endpoint
- No `shell=True`
- No shell-string commands
- No deployment from arbitrary branches
- Dirty-tree refusal before automatic mutation
- File lock against concurrent runs
- Non-root user execution
- Repository-scoped read-only deploy keys recommended
- Secrets kept in protected environment files outside Git
- Rotating logs with bounded size

## Host permissions

Run the agent as the same unprivileged user that owns the checkouts and user services. Do not run it as root. Grant that user access only to the repositories, service units, state directories, and health endpoints it needs.

The registry can authorize executable commands. Protect it accordingly:

```bash
chmod 600 ~/.config/deployment-agent/config.json
chmod 700 ~/.config/deployment-agent
```

Environment files should use the same restrictions.

## GitHub controls

- Protect deployment branches.
- Require pull requests and automated tests where practical.
- Prevent force-pushes to deployment branches.
- Prefer signed commits or verified contributors for higher-risk systems.
- Use one deploy key per private repository.
- Give deployment keys read access only.

## Application data

Do not store mutable production state in Git checkouts. This includes:

- SQLite databases
- uploads and generated documents
- runtime-edited prompts
- logs
- model artifacts
- caches
- `.env` files
- credentials and API keys

Relocate these into protected state/configuration directories and reference them through environment variables or application configuration.

## Rollback limitations

Code rollback cannot reverse destructive database migrations, external API writes, sent messages, or other side effects. Applications performing those operations need their own transactional migration and recovery strategy.
