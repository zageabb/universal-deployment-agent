# UDA V2 Approval Centre — review-only first increment

**Status:** draft PR #27 only; no production deployment, migration, approval-token
issuance, secret changes or systemd activation.

## User interface

The existing authenticated UDA dashboard has an **Approvals** navigation link
to `GET /approvals`. The page displays:

- the current DEV-020 V2-only **known review gates** for eleven application
  manifests from `tools.validate_v2_only.REVIEW_GATES` (read-only source
  inventory, **not** authoritative live host status);
- pending, approved, revoked and expired review requests;
- a form for administrators to create a **registered-application** request
  tied to an exact 40-character Git commit SHA, operation, scope, rationale
  and expiry (1–168 hours);
- an approve/deny/revoke action with mandatory reason and the existing
  dashboard-wide CSRF guard;
- a persistent, append-only-through-the-UI audit history including UTC time,
  request ID, action, actor and reason.

The dashboard's existing HTTP Basic **admin** identity is the only account
permitted to access or mutate records. The audit actor is currently recorded
as `admin`; it does **not** attribute decisions to distinct human users
sharing that credential. Per-user UDA identity and RBAC are a separate
hardening milestone, not provided by this increment.

## Persistence

Records are stored outside Git, by default in
`<directory containing dashboard config>/approvals.sqlite3`, or at the
explicit `approval_centre_store` absolute path in the protected dashboard
configuration. The parent must exist and the SQLite file is created with
mode 0600. No credentials, signing keys, secret values or uploaded files are
stored. Scope/reasons may contain operationally sensitive details and must
not contain secret values or business records.

For production readiness, the administrator must verify the real storage
path, filesystem owner and permissions, backup/restore, retention,
concurrency/multiple dashboard processes, and separation from protected
configuration. The dashboard does not silently create a remote or shared
database.

## Critical separation of authority

**A recorded 'approved' review request is informational and never a
deployment, staging, systemd, database-write, migration or capability
authorisation.** This implementation does not invoke, import, mint or revoke
onboarding tickets, `onboarding_v2_approval` review attestations,
independent signer keys, executable command bundles, UDA config mutations,
live database privileges or production deployment actions.

Revocation blocks future reliance on that *record*; it does not invalidate
independently signed tickets/receipts or undo work already executed.
Execution systems must continue to enforce their original independent,
commit-pinned, one-time approval checks. Do not wire a privileged executor
to this SQLite approval bit. The known V2 acceptance gates stay visible
regardless of review decisions, until independently verified and the
source-tracked gate list is updated.

The known-gates section currently covers the eleven V2-only application
drafts. It does not yet dynamically discover every gate in existing V1/V2
deployments, the six special design-only holds, or connected applications.
Those should be added later through a *read-only* unified source of truth,
not by guessing or auto-approving them.

## Independent test plan

```bash
python -m pytest -q tests/test_approval_centre.py tests/test_dashboard.py
python -m pytest -q
```

Tests include create/approve/deny/revoke and audit-event ordering, expiry,
private SQLite permissions, unknown application and invalid source commit
rejection, basic-auth + CSRF, no systemd execution, and known review gates
remaining visible after approvals. Run against the actual PR #27 checkout
with installed development requirements in an isolated environment. Existing
GitHub Actions are billing-blocked; **test files committed is not proof they
have passed**.

## Next release gates

1. Run complete independent UDA test suite and explicit Approval Centre
   acceptance on the current PR head.
2. Review admin identity/RBAC, protected storage and audit durability;
   include stale review items and proper request expiry.
3. Decide how to ingest externally signed or host-derived requests without
   weakening the current `onboarding_v2_approval` trust boundary.
4. Prove that revocation is enforced by any future trusted execution
   authority before claiming *operational* revocation.
5. Keep PR #27 draft and do not install or enable until explicit
   deployment-owner approval.
