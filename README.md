# Universal Git Deployment Agent

## Ubuntu server deployment

Verified on **14 September 2026** against the listeners, user systemd services,
Docker port mappings and deployment registry on `192.168.1.249`.

| Endpoint | Host TCP port | LAN URL |
|---|---:|---|
| Authenticated dashboard | 5030 | http://192.168.1.249:5030/ |
| Application Home | 5048 | http://192.168.1.249:5048/ |

Checkout: `/home/zageabb/ollama-chat/universal-deployment-agent`.

Installed runtime: `/home/zageabb/.local/share/deployment-agent`.

These are **user** systemd units. Inspect them with:

```bash
systemctl --user status deployment-agent-dashboard.service deployment-agent-home.service
systemctl --user cat deployment-agent-dashboard.service deployment-agent-home.service
```

Local verification URL: `http://127.0.0.1:5030/`. The dashboard returns HTTP 401 until authenticated.

Development defaults and container-internal ports elsewhere in this repository
may differ from this host deployment. Use the live ports above when accessing
this Ubuntu server; do not start a second copy on a port already occupied.

[Complete Ubuntu port inventory](https://github.com/zageabb/universal-deployment-agent/blob/main/UBUNTU_PORTS.md).

A small, dependency-free deployment poller for multiple applications on one Linux host. It checks configured Git branches, fast-forwards clean repositories, runs allowlisted update commands, restarts the corresponding systemd user service, verifies its health endpoint, and rolls back a failed deployment.

The Flask dashboard shows agent version and last-run status, application health, commits and deployment results. Authorized applications can be checked and updated immediately from their card. It listens on port 5030 and requires HTTP Basic authentication: username `admin`, password from `dashboard_token` in the local configuration. Open `http://SERVER:5030` from the trusted network.

## Application Home

The optional read-only home page lists enabled applications from the same UDA
registry, with Context Studio's navy and blue styling. Cards open in a new tab.
It runs on port **5048**; port 5049 remains available for the existing pgAdmin
installation. After installation, start it with:

```bash
systemctl --user enable --now deployment-agent-home.service
```

Open `http://SERVER:5048/`. The page refreshes its directory every minute without
reloading the page. Libraries and entries with `show_on_home: false` are omitted.
When the authenticated portal is exposed through both the public HTTPS proxy and
an explicit LAN HTTP address, session cookies follow the effective request scheme:
they remain `Secure` through HTTPS and can complete login on the trusted LAN URL.
Use `app_url` when the application's front end differs from its health endpoint
(for example, Context Studio uses 5075 while its health endpoint uses 8074).
Without `app_url`, the health URL's origin is used with `/` as the path. Loopback
hosts are replaced by the hostname used to open the home page. An explicit
`--public-host` can override that hostname. `display_name` optionally supplies a
friendly card title.

The launcher can operate as an authenticated application portal by setting
`portal_auth_enabled`. Accounts are stored in a dedicated SQLite identity
database; verification and password reset messages use SMTP credentials supplied
through `UDA_SMTP_PASSWORD`. UDA groups double as application entitlements when
an application declares `allowed_groups`.

Public ingress is opt-in per application. `proxy_config.py` generates a Caddy
configuration only for enabled entries with `proxy_enabled: true`; unpublished
registry entries never become routes. The generated path is
`/apps/<proxy_slug>/` and the application must support `X-Forwarded-Prefix`.
The proxy delegates every application request to `/auth/check`, so hiding a card
is not the access-control boundary.
Its JSON endpoint exposes only names, titles, links, initials, and addresses;
registry secrets, filesystem paths, and deployment commands are never included.

`proxy_migration_agent.py` can monitor the live registry for newly deployed
applications that carry `tests/test_uda_subpath.py`. Every ten minutes it considers
only enabled, launcher-visible, unproxied services whose checkout is clean and
exactly matches its configured remote branch. It runs the repository's full test
suite, probes the live backend with `X-Forwarded-Prefix`, backs up and atomically
updates the registry, reloads Caddy, and verifies that unauthenticated public
ingress remains blocked. A failed publish restores the previous registry and
routes. It never merges branches or edits application source. Results are recorded
in `~/.local/state/deployment-agent/proxy-migration.json` and the systemd journal.
Groups can be managed from **5030 → Manage groups** without editing JSON. The
interface can create, rename, reorder and delete groups, and assign each
registered application. The ordered group list is stored in the registry and is
used by both 5030 and 5048. Existing application-level `group` values are
imported automatically; apps without a group appear under `Other`. Each page
remembers the selected group for the current browser tab.
Each destination retains its own authentication. The management dashboard on
5030 remains separate and authenticated.

## Documentation

- [Architecture and deployment lifecycle](docs/architecture.md)
- [Installation and initial configuration](docs/installation.md)
- [Registry reference and application onboarding](docs/configuration.md)
- [Operations, monitoring, and recovery](docs/operations.md)
- [Security model](docs/security.md)
- [Scheduled application jobs](docs/scheduled-jobs.md)
- [Ollama Chat reference deployment](docs/ollama-chat.md)

## Explicit GitHub Actions trigger

UDA includes a generic local command for dispatching an existing GitHub Actions
workflow and returning a machine-readable result. It requires an authenticated
GitHub CLI with permission to run Actions in the target repository.

```bash
uda-trigger-ci \
  --repo OWNER/REPOSITORY \
  --workflow ci.yml \
  --ref main \
  --wait
```

The JSON result always reports whether GitHub accepted the dispatch. When the
new run becomes visible it also contains its run ID, URL, status, conclusion and
commit SHA. Without `--wait`, the command returns as soon as the new queued or
in-progress run is identified. With `--wait`, it polls until completion and
returns a non-zero exit status for failed, cancelled or timed-out runs.

This is a local outbound capability, not an unauthenticated HTTP endpoint. It
does not store a token in the UDA registry; authentication remains managed by
GitHub CLI in the invoking user's protected configuration.

## Safety model

- Applications are disabled unless explicitly enabled.
- Enabled applications default to monitor-only until `auto_deploy` is explicitly set to `true`.
- Dirty working trees are never modified.
- Updates must be fast-forwardable from the configured remote branch.
- Only argument-array commands stored in the local registry can run.
- A host-wide lock prevents concurrent deployments.
- Failed restarts or health checks restore the previous commit.
- Scheduled jobs run independently as generated systemd user services and timers; they never participate in deployment rollback.
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
