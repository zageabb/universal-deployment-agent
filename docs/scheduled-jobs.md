# Scheduled application jobs

UDA can reconcile declarative application jobs into independent systemd user
oneshot services and timers. UDA still owns source update, application restart,
and health validation. A timer starts only its generated oneshot service; it
never starts another copy of the web application.

## Registry schema

Add `scheduled_jobs` to an application. Application and job names use lowercase
letters, digits, and internal hyphens so generated unit names are predictable.

```json
"scheduled_jobs": [
  {
    "name": "daily-maintenance",
    "description": "Run daily application maintenance",
    "enabled": true,
    "schedule": "daily",
    "time": "06:00",
    "persistent": true,
    "command": ["./venv/bin/python", "manage.py", "maintenance"],
    "environment_file": "/home/example/.config/example/app.env"
  }
]
```

`command` is a non-empty argument array, never a shell string. A relative
executable is resolved against the application's `repo_path`; remaining
arguments are passed literally. `repo_path` is also the service working
directory. `environment_file` is optional and overrides the application's
field of the same name. Its contents are never copied into status, logs,
documentation, or the dashboard. `persistent` defaults to true, so systemd can
run a missed occurrence after the host/user manager returns.

Disabled jobs and jobs belonging to disabled applications have their formerly
managed units disabled and removed on the next normal UDA run.

## Schedules

| `schedule` | Additional fields | Generated `OnCalendar` example |
|---|---|---|
| `daily` | `time` in `HH:MM` | `*-*-* 06:00:00` |
| `hourly` | optional integer `minute`, default 0 | `*-*-* *:00:00` |
| `weekly` | full English `weekday` and `time` | `Mon *-*-* 06:00:00` |
| `on-calendar` | non-empty `on_calendar` expression | passed to systemd unchanged |

Daily, hourly, and weekly forms deliberately prevent sub-hour schedules. Use
the explicit advanced `on-calendar` form only when the host administrator has
reviewed a different frequency. Validate advanced expressions with
`systemd-analyze calendar 'EXPRESSION'` on the host.

## Generated units and lifecycle

For application `ledgerone` and job `recurring-transactions`, UDA owns:

```text
~/.config/systemd/user/uda-ledgerone-recurring-transactions.service
~/.config/systemd/user/uda-ledgerone-recurring-transactions.timer
```

On a normal run UDA writes files only when content changed, calls
`systemctl --user daemon-reload` only after a write/removal, enables and starts
required timers, and restarts a timer only when its timer definition changed.
Obsolete units are disabled and removed. Files with a similar name but without
UDA's managed marker are never removed. Dry runs validate and report without
changing unit files or timer state.

The status JSON and authenticated dashboard report the schedule, enabled state,
timer activity, next/previous trigger, last service result, and generated unit
names. The dashboard's **Run now** action invokes the same generated service as
the timer; it does not implement a second task runner.

Job failure is independent of deployment. It is reported by systemd and does
not roll back application source. Database migrations remain deployment
`update_commands`, not scheduled jobs.

## LedgerOne recurring work generation

Add this job to the host-local LedgerOne application entry (merge it with the
existing fields; do not replace secrets or unrelated settings):

```json
"scheduled_jobs": [
  {
    "name": "recurring-transactions",
    "description": "Generate LedgerOne recurring transaction work items",
    "enabled": true,
    "schedule": "daily",
    "time": "06:00",
    "persistent": true,
    "command": [
      "./venv/bin/flask",
      "--app",
      "run.py",
      "generate-recurring-transactions"
    ]
  }
]
```

The command creates due User Actions/work items only. It does not post entries;
LedgerOne's human review, approval, and posting controls remain authoritative.
The existing first-authenticated-request daily fallback may remain enabled.

## Install, inspect, and trigger

After pulling and installing UDA, run one normal reconciliation:

```bash
cd ~/ollama-chat/universal-deployment-agent
git pull --ff-only
./install.sh
~/.local/share/deployment-agent/deploy_agent.py \
  --config ~/.config/deployment-agent/config.json
```

Inspect and operate the LedgerOne example:

```bash
systemctl --user list-timers
systemctl --user status uda-ledgerone-recurring-transactions.timer
systemctl --user status uda-ledgerone-recurring-transactions.service
journalctl --user -u uda-ledgerone-recurring-transactions.service
systemctl --user start uda-ledgerone-recurring-transactions.service
```

If the timer is missing, first run UDA normally and inspect
`journalctl --user -u deployment-agent.service` plus the configured rotating
log. If it is inactive, confirm the application and job are enabled, then rerun
UDA. For command failures, inspect the service journal, verify the repository
path and executable, and confirm the protected environment file is readable by
the unprivileged deployment user. User lingering must be enabled for timers to
run when nobody is logged in (`loginctl enable-linger "$USER"`, subject to host
policy).
