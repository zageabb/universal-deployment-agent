# UDA V2 Approval Centre — review-only first increment

**Status:** draft PR #27 only; no production deployment, migration, approval-token
issuance, secret changes or systemd activation.

## User interface

The existing authenticated UDA dashboard has an **Approvals** navigation link
to `GET /approvals`. The page displays:

- the current DEV-020 V2-only **known review gates** for eleven executable
  application manifests, plus six special **design-only** cases from `tools.validate_v2_only.REVIEW_GATES` (read-only source
  inventory, **not** authoritative live host status);
- pending, approved, revoked and expired review requests;
- a form for administrators to create a **registered-application** request
  tied to an exact 40-character Git commit SHA, operation, scope, rationale
  and expiry (1–168 hours);
- an approve/deny/revoke action with mandatory reason and the existing
  dashboard-wide CSRF guard;
- a persistent, append-only-through-the-UI audit history including UTC time,
  request ID, action, actor and reason.

The dashboard's existing HTTP Basic **admin** credential still gates
page access. In addition, every **write** to the Approval Centre now
requires separate named reviewer reauthentication using the
`approval_reviewer_accounts` protected dashboard configuration. Individual
entries must have `username`, `role` (`reviewer` or `approver`)
and `password_hash` generated using
`werkzeug.security.generate_password_hash`. A reviewer can submit
requests; only an approver can approve, deny or revoke. If no accounts
are configured, the centre is read-only (writes fail closed).

Example shape (hash and identity placeholders, never plaintext):
```json
{
  "approval_reviewer_accounts": [
    {"username": "operator-1", "role": "reviewer", "password_hash": "<werkzeug-hash>"},
    {"username": "approver-1", "role": "approver", "password_hash": "<werkzeug-hash>"}
  ]
}
```
Do not copy example placeholders into a live config. Keep real values in
the protected host configuration, not source control. Require HTTPS for
password-bearing POST requests; never store, log or display form passwords.
Identity attribution is to configured credentials, not external SSO identity
proof. Anyone sharing a named credential is still indistinguishable.
Future integration with the portal's personal identity store should occur
only after the UDA Home/dashboard trust boundary has been reviewed.

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

The known-gates section now covers eleven V2-only executable manifest drafts
and six design-only holds (ScreenCraft, Camper Power Studio, DB Migration,
ShadowPrompt Lab, protected UDA self-upgrade and Application Home). It additionally lists the twenty historic V1→V2 conversion repositories
from the immutable Git parity validator as a read-only review inventory.
It does not infer current per-application acceptance from that source list
and does not dynamically discover connected applications or live host approval authority. These
remain source-tracked review metadata, not real-time host gate status.

## Independent test plan

```bash
# From a clean, disposable checkout of feature/uda-v2-independent-validation:
# Choose a new private output directory outside the repository.
bash tools/test_approval_centre_independent.sh /path/to/NEW-private-uda-approval-evidence
```
The runner records the exact Git commit, Python version, targeted dashboard
tests and full UDA pytest output, and rejects overwrite/nonreview branches.
It never deploys. Make sure the isolated environment has the normal UDA
development dependencies installed.

Tests include create/approve/deny/revoke and audit-event ordering, expiry,
private SQLite permissions, unknown application and invalid source commit
rejection, basic-auth + CSRF, no systemd execution, and known review gates
remaining visible after approvals. Run against the actual PR #27 checkout
with installed development requirements in an isolated environment. Existing
GitHub Actions are billing-blocked; **test files committed is not proof they
have passed**.

## Independent acceptance update and optional storage preflight — 20 November 2026

On `m901-lenovo` the operator ran
`tools/test_approval_centre_independent.sh` on clean, isolated checkout
**`859619e0d9a1d08d52907f92f14c610b6d3f1995`**.
The operator supplied these results:

- Approval Centre and dashboard: **38 passed in 5.73 seconds**.
- Full UDA pytest regression: **550 passed in 41.59 seconds**.
- Runner: `targeted_exit=0`; `full_exit=0`.

This establishes independent functional regression acceptance for that SHA.
**Later changes must be retested**; the test counts above are not a pass
on any later commit. PR #27 remains draft; security/host readiness is distinct.

The new `tools/approval_store_preflight.py` inspects only an existing
SQLite review store in read-only mode. It checks file mode, local owner,
audit triggers, expected tables and SQLite integrity without exporting
request or audit rows or modifying schema. It is optional and **not**
needed if the Approval Centre has never been enabled (no store exists).

```bash
# On the server with access to the EXISTING review DB; do not pass config.json
# or secrets. Only use after the exact review store path is verified.
python3 tools/approval_store_preflight.py --store /absolute/path/to/approvals.sqlite3
```

If there is no actual approval database yet, leave it uncreated and use
the six isolated fixture tests instead. Never point the preflight at
the real application database or a privileged production secret store.

### Explicit network-binding hold

The operator requested that the existing dashboard **remain bound to
`0.0.0.0:5030` for now**. The reviewed effective user-level
systemd `ExecStart` confirms this binding; no service, firewall or Caddy
change is authorised here. The direct-port reachability, TLS termination,
firewall and route authentication have not yet been independently verified.
This is an explicit **transport-security review gate**, not a reason to
invent HTTPS evidence or silently change the dashboard binding.
Do not enable approval password submission on a remotely reachable
plaintext HTTP path until transport security is independently accepted.

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

## Independent backend reproduction — 20 November 2026

An isolated copy of the `approval_centre.py` backend fetched from PR #27
was reconstructed locally with Python 3.13.5 and SQLite. Eight tests passed:
request/approve/revoke lifecycle, denial, expiration, bad source SHA,
legacy underscores, five simultaneous conflicting approval attempts,
private file permissions and symlink rejection. Concurrency generated
only one successful approval and one `approved` audit event. This was
**not** a full cloned-PR Flask integration, pytest suite or production
storage acceptance. Separate PR tests now cover the same concurrency
and the six design-only hold sources; these new GitHub-head tests have
not been independently executed in this session.

## Stronger audit protection

The review audit table now has SQLite triggers that reject direct UPDATE
and DELETE operations, supplementing private 0600 file creation and
transactional request/decision plus audit writes. The audit attribution
includes the reauthenticated named reviewer/approver username. These are
**ordinary application-level protections**: a filesystem administrator
or SQLite database owner can still drop triggers or modify the file.
Cryptographic tamper evidence, backup/restore integrity and external
read-only checkpoints remain production hardening gates. Do not claim
append-only durability against a privileged host compromise.

## Trusted revocation authority

See `docs/v2-trusted-revocation-design.md`. It proposes a separately
signed, externally checkpointed revocation ledger checked by the trusted
attestation verifier. This is a **design only**, not implemented token
revocation. An Approval Centre revoke event does not invalidate any
previously signed or consumed token.

### Current integration execution limit

The present ChatGPT container has Python/pytest/sqlite3 but lacks Flask and
Werkzeug, and cannot install them from the package index. **Flask/dashboard
integration is still NOT independently passed** in the current environment.
A disposable backend reconstruction including SQL audit triggers passed
9/9 tests, but is not the same as running the actual GitHub PR head.
Do not merge/deploy based solely on these backend tests. Use the independent
runner above on a development machine with dependencies available and attach
the logs/evidence to PR #27 for review.
