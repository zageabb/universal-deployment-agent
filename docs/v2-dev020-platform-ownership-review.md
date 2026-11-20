# DEV-020 — UDA self-management and Application Home ownership review

**Status: design-only, read-only integration. No executable self-deployment
manifest or new independent Application Home registration is authorised.**

## Source ownership evidence

The same `zageabb/universal-deployment-agent` repository owns:

- `deploy_agent.py`: existing V1 deployment poller and registry reconciliation
- `home.py`: authenticated Application Home backed by that shared registry
- `dashboard.py`: deployment management dashboard
- `systemd/deployment-agent-home.service`: existing home service using
  the UDA-managed Python virtualenv and protected registry configuration
- `systemd/deployment-agent-dashboard.service`: existing management service
- `systemd/deployment-agent.service`: oneshot deployment worker

Application Home **is a UDA-owned component**, not an autonomous Git
deployment. A second independent lifecycle owner would risk replacing the
owner of authentication, user access, dashboard, registry or service units.

## Mandatory boundaries

1. **Self-management must remain bootstrap-protected**. An application
   deployment worker must not be able to upgrade, remove or restart its own
   trusted bootstrap or authentication layer as if it were an ordinary app.
2. Application Home should be modeled as a component of the same protected
   platform graph, with one explicit lifecycle owner. Preserve exact
   systemd unit names, runtime virtualenv, user scope and registry paths
   only after live read-only reconciliation.
3. `home.py` accesses the portal user/group database and login/session
   functionality. No generated V2 manifest may grant it new database-write,
   email or user-administration permissions by inference.
4. `dashboard.py` includes operations that can change the registry and
   service state. Do not equate dashboard HTTP health with permission to
   run its actions; operator approval and existing controls remain mandatory.
5. Existing oneshot timers, locks, config and protected production
   installation must be preserved through a separately rehearsed
   bootstrap/rollback plan. Changes to the UDA v2 schema or validation tool
   do not constitute a production activation approval.
6. The known `db-migration` unrelated deployment-agent test exception
   remains a separate production issue, not a reason to bypass the gate.
7. No ChatGPT custom MCP bridge is required; keep GitHub-native reporting
   and independent test evidence.

## Required gates

- [ ] Read-only inventory: effective UDA/Home/Dashboard user systemd units,
      timers, working directories, versions, Caddy auth routing, config and
      portal DB **paths and secret reference names only**.
- [ ] Confirm UDA V2 `kind: platform` and `strategy: bootstrap-only`
      schema/semantic requirements and lifecycle `owner` model.
- [ ] Design a single protected platform manifest with Home and Dashboard as
      declared components, not duplicate app ownership.
- [ ] Prove that deployment-agent self-update cannot be triggered by an
      ordinary registry entry, unauthenticated request or workflow dispatch.
- [ ] Test independent re-install/recovery from disposable bootstrap fixture
      against the last known good version and systemd/timer state.
- [ ] Obtain explicit production owner sign-off for the platform upgrade,
      separately from merging review-only PR #26 or #27.

Until then, **Application Home and UDA self-upgrade stay design-only**.
No `uda.v2.yaml` for the platform, no service restart, no registry mutation,
no Caddy reload, no database write and no deployment activation is performed.
