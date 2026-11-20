# UDA V2 — Trusted signed-attestation revocation design

**Status: proposal, not deployed or wired to privileged execution.**

## Authority separation

The dashboard Approval Centre stores *administrative review records* only.
A record marked `approved` never creates a signed attestation or grants a
deployment capability. A record marked `revoked` invalidates only that
administrative record; it cannot revoke a separately signed token without
the independent authority's own revocation evidence.

The existing `onboarding_v2_approval.py` signs a unit bundle's SHA-256,
source commit, application, reviewer identity, action and a random one-time
nonce with an independently held key. Its verifier accepts `review_only`
receipts, never installation. The existing one-use receipt store already
prevents token replay after consumption.

## Proposed trusted revocation registry

A separate, non-dashboard, protected authority maintains an append-only
revocation ledger keyed by the **digest of the signed token** (not the
raw bearer token) and recording:

- token SHA-256, approval nonce, application, source commit, bundle digest
- independent authority actor ID, issued-at and revoked-at UTC
- precise reason, request/ticket ID and monotonic ledger sequence
- an authority signature and previous-record hash chain
- a protected ledger generation/checkpoint outside the application DB

No secret or raw token is placed in the dashboard, Git repository, logs or
review database. Only the independent trusted authority can write a signed
revocation event; dashboards can read a sanitised projection of outcomes.

## Verifier contract

Before **any** future trusted execution authority accepts a signed token:

1. Validate canonical token, cryptographic signature, action, reviewer
   scope, application, immutable commit and bundle digest.
2. Check expiry and one-use nonce receipt.
3. Validate the independently signed revocation ledger and latest checkpoint.
4. Reject if token digest or nonce is revoked, if the ledger is unavailable,
   corrupt or stale beyond an explicit policy limit, or if the checkpoint
   has rolled back.
5. Atomically consume the token and commit the authorised transition
   under one executor-side lock/transaction; never depend on a dashboard
   SQLite field or a frontend request to enforce it.

Revocation does **not** undo work previously performed and does not grant
authority for recovery, rollback or migration. Those require separate
scoped, signed permissions. Review-only tokens cannot be upgraded to
execution permissions by a revocation registry or dashboard decision.

## Concurrency and security acceptance fixtures

- Unsigned, forged-signature, wrong-key, wrong-app, wrong-commit and
  wrong-action revocation records are rejected.
- A correctly signed revocation before consumption prevents acceptance.
- Concurrent approve/revoke and consume/revoke races resolve under one
  authoritative ledger lock; exactly one outcome is committed.
- Revoking after consumption is audited but cannot roll back completed work.
- Replay, truncation, checkpoint rollback, missing ledger, and stale cache
  fail closed.
- An Approval Centre `approved` or `revoked` bit cannot override the
  authoritative revocation check; deployment, database and systemd APIs
  cannot call the dashboard record directly.
- Tests run on disposable keys, files and non-privileged fake executors.

## Release gate

Do not connect the approval page to `onboarding_v2_approval.py` or a
deployment executor until the external authority/key custody, replication,
offline revocation availability, operational failure policy, protected
checkpoint, individual identity, and independent test evidence are
explicitly reviewed. No production activation is authorised here.
