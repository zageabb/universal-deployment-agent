"""Independent, no-deployment Approval Centre lifecycle and dashboard tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import dashboard
from approval_centre import ApprovalError, create_request, decide, overview

SHA = "a" * 40
ADMIN = {"Authorization": "Basic YWRtaW46c2VjcmV0"}


def client_for(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "dashboard_token": "secret",
        "applications": [{"name": "example", "enabled": False, "branch": "main",
                          "repo_path": str(tmp_path), "auto_deploy": False}],
        "approval_centre_store": str(tmp_path / "review.sqlite3"),
    }))
    client = dashboard.create_app(cfg).test_client()
    return client, {"csrf_token": client.application.config["CSRF_TOKEN"]}


def test_approval_record_lifecycle_and_append_only_audit(tmp_path):
    store = tmp_path / "approvals.sqlite3"
    ident = create_request(store, application="example", action="database-migration",
                           scope="staging-only schema v1", source_sha=SHA,
                           reason="Reviewed disposable staging test evidence")
    requests, audit = overview(store)
    assert requests[0]["status"] == "pending"
    assert audit[0]["event"] == "requested"
    assert store.stat().st_mode & 0o077 == 0
    decide(store, ident, decision="approved", reason="Staging migration rehearsal accepted")
    requests, audit = overview(store)
    assert requests[0]["effective_status"] == "approved"
    assert audit[0]["event"] == "approved"
    with pytest.raises(ApprovalError, match="Only pending"):
        decide(store, ident, decision="approved", reason="Cannot approve review twice")
    decide(store, ident, decision="revoked", reason="New evidence invalidated approval")
    requests, audit = overview(store)
    assert requests[0]["status"] == "revoked"
    assert [event["event"] for event in audit] == ["revoked", "approved", "requested"]
    with pytest.raises(ApprovalError, match="Only approved"):
        decide(store, ident, decision="revoked", reason="Cannot revoke twice again")


def test_denied_requests_never_reactivate(tmp_path):
    store = tmp_path / "approvals.sqlite3"
    ident = create_request(store, application="example", action="proxy-route",
                           scope="temporary alias", source_sha=SHA,
                           reason="Investigate existing alias route")
    decide(store, ident, decision="denied", reason="Insufficient route evidence")
    with pytest.raises(ApprovalError):
        decide(store, ident, decision="approved", reason="Cannot change denied status")


def test_expired_approval_cannot_be_revoked_or_reapproved(tmp_path):
    from datetime import timedelta
    import sqlite3
    import approval_centre
    store = tmp_path / "approvals.sqlite3"
    ident = create_request(store, application="example", action="deploy",
                           scope="disposable deployment", source_sha=SHA,
                           reason="Disposable release evidence review")
    decide(store, ident, decision="approved", reason="Scoped one-time review only")
    with sqlite3.connect(store) as conn:
        conn.execute("UPDATE requests SET expires_at=? WHERE id=?", (
            (approval_centre.now_utc() - timedelta(minutes=1)).isoformat(), ident))
    assert overview(store)[0][0]["effective_status"] == "expired"
    with pytest.raises(ApprovalError, match="Expired"):
        decide(store, ident, decision="revoked", reason="Too late to revoke expired review")


def test_dashboard_approval_routes_are_authenticated_and_csrf_protected(tmp_path):
    client, csrf = client_for(tmp_path)
    assert client.get("/approvals").status_code == 401
    assert client.get("/approvals", headers=ADMIN).status_code == 200
    assert client.post("/approvals/request", data=csrf).status_code == 401
    assert client.post("/approvals/request", headers=ADMIN).status_code == 403
    assert client.post("/approvals/request", headers=ADMIN,
                       data={"csrf_token": "bad"}).status_code == 403
    assert b"Approval Centre" in client.get("/approvals", headers=ADMIN).data


def test_dashboard_approve_and_revoke_do_not_execute_services(tmp_path):
    client, csrf = client_for(tmp_path)
    request_data = {
        **csrf, "application": "example", "action": "database-write",
        "scope": "synthetic staging records", "source_sha": SHA,
        "reason": "Read-only synthetic test and signed review reference",
        "ttl_hours": "24",
    }
    with patch("dashboard.subprocess.run") as run:
        response = client.post("/approvals/request", headers=ADMIN, data=request_data)
        assert response.status_code == 302
        store = tmp_path / "review.sqlite3"
        records, _ = overview(store)
        ident = records[0]["id"]
        approve = client.post(f"/approvals/{ident}/decision", headers=ADMIN,
                              data={**csrf, "decision": "approved",
                                    "reason": "Synthetic review only, no execution"})
        assert approve.status_code == 302
        revoke = client.post(f"/approvals/{ident}/decision", headers=ADMIN,
                             data={**csrf, "decision": "revoked",
                                   "reason": "Synthetic review revoked explicitly"})
        assert revoke.status_code == 302
        run.assert_not_called()
    assert overview(store)[0][0]["status"] == "revoked"


def test_unknown_app_and_invalid_source_sha_cannot_be_requested(tmp_path):
    client, csrf = client_for(tmp_path)
    request = {**csrf, "application": "missing", "action": "deploy",
               "scope": "staging only", "source_sha": SHA,
               "reason": "Review reason longer than ten characters"}
    assert client.post("/approvals/request", headers=ADMIN, data=request).status_code == 400
    request["application"] = "example"
    request["source_sha"] = "main"
    assert client.post("/approvals/request", headers=ADMIN, data=request).status_code == 400
    assert overview(tmp_path / "review.sqlite3")[0] == [] if (
        tmp_path / "review.sqlite3").exists() else True
