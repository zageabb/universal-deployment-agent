"""Persistent review-only UDA Approval Centre.

This registry NEVER signs onboarding attestation tokens, changes a deployment
registry, or grants a service/DB capability. Approval here is a human review
record; execution requires the existing independent authority and gates.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import closing
import os
from pathlib import Path
import re
import sqlite3
import uuid

APP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
ACTIONS = {
    "deploy", "database-migration", "database-write", "restore",
    "backup-verification", "service-change", "router-polling",
    "network-discovery", "secret-change", "proxy-route", "other",
}
STATUSES = {"pending", "approved", "denied", "revoked"}
MAX_REASON = 1500
MAX_LABEL = 160


class ApprovalError(ValueError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _store(path: Path) -> sqlite3.Connection:
    path = path.expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.parent.is_dir():
        raise ApprovalError("Approval store must be an absolute non-symlink path in an existing directory")
    if path.exists():
        if not path.is_file() or path.stat().st_mode & 0o077:
            raise ApprovalError("Approval store must be a private regular file")
    else:
        # sqlite3.connect() otherwise inherits process umask and can create
        # world-readable approval records on common 022 hosts.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            raise ApprovalError("Approval store changed while opening") from None
        else:
            os.close(fd)
    conn = sqlite3.connect(path, timeout=5)
    if path.stat().st_mode & 0o077:
        conn.close()
        raise ApprovalError("Approval store permissions are not private")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS requests (
            id TEXT PRIMARY KEY, application TEXT NOT NULL, action TEXT NOT NULL,
            scope TEXT NOT NULL, source_sha TEXT NOT NULL,
            reason TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            decided_at TEXT, decided_by TEXT, decision_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS audit (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL, event TEXT NOT NULL,
            actor TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL
        );
    """)
    return conn


def _details(request: sqlite3.Row | dict, *, now: datetime) -> dict:
    value = dict(request)
    value["effective_status"] = (
        "expired" if value["status"] in {"pending", "approved"}
        and datetime.fromisoformat(value["expires_at"]) <= now else value["status"]
    )
    return value


def overview(path: Path) -> tuple[list[dict], list[dict]]:
    with closing(_store(path)) as conn:
        requests = [_details(item, now=now_utc()) for item in conn.execute(
            "SELECT * FROM requests ORDER BY created_at DESC, id DESC LIMIT 1000")]
        audit = [dict(item) for item in conn.execute(
            "SELECT * FROM audit ORDER BY event_id DESC LIMIT 1000")]
    return requests, audit


def create_request(path: Path, *, application: str, action: str, scope: str,
                   source_sha: str, reason: str, actor: str = "admin",
                   ttl_hours: int = 24) -> str:
    if not APP.fullmatch(application) or action not in ACTIONS:
        raise ApprovalError("Invalid application or approval action")
    if (not 1 <= ttl_hours <= 168 or not 1 <= len(scope.strip()) <= MAX_LABEL
            or len(reason.strip()) < 10 or len(reason) > MAX_REASON
            or not SHA.fullmatch(source_sha)):
        raise ApprovalError("A scoped, reasoned, commit-pinned request and 1-168h expiry are required")
    now = now_utc()
    ident = uuid.uuid4().hex
    with closing(_store(path)) as conn, conn:
        conn.execute("INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
            ident, application, action, scope.strip(), source_sha,
            reason.strip(), "pending", _utc(now),
            _utc(now + timedelta(hours=ttl_hours)), None, None, None))
        conn.execute("INSERT INTO audit(request_id,event,actor,at,reason) VALUES(?,?,?,?,?)",
                     (ident, "requested", actor, _utc(now), reason.strip()))
    return ident


def decide(path: Path, ident: str, *, decision: str, reason: str,
           actor: str = "admin") -> dict:
    if not re.fullmatch(r"[0-9a-f]{32}", ident) or decision not in {"approved", "denied", "revoked"}:
        raise ApprovalError("Invalid request or decision")
    if len(reason.strip()) < 10 or len(reason) > MAX_REASON:
        raise ApprovalError("A decision reason of at least 10 characters is required")
    now = now_utc()
    with closing(_store(path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        record = conn.execute("SELECT * FROM requests WHERE id=?", (ident,)).fetchone()
        if not record:
            raise ApprovalError("Approval request not found")
        before = record["status"]
        if decision in {"approved", "denied"} and before != "pending":
            raise ApprovalError("Only pending requests can be approved or denied")
        if decision == "revoked" and before != "approved":
            raise ApprovalError("Only approved requests can be revoked")
        if datetime.fromisoformat(record["expires_at"]) <= now:
            raise ApprovalError("Expired requests cannot change decision")
        conn.execute("""UPDATE requests SET status=?, decided_at=?,
                        decided_by=?, decision_reason=? WHERE id=?""",
                     (decision, _utc(now), actor, reason.strip(), ident))
        conn.execute("INSERT INTO audit(request_id,event,actor,at,reason) VALUES(?,?,?,?,?)",
                     (ident, decision, actor, _utc(now), reason.strip()))
        return _details(dict(record) | {"status": decision}, now=now)


def read_only_approval_notice() -> str:
    return ("Approval Centre decisions record review only; they never "
            "authorise staging, deployment, migration or service execution.")
