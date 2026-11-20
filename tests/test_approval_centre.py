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
    store = tmp_path / "review.sqlite3"
    if store.exists():
        assert overview(store)[0] == []


def test_approval_page_displays_unsatisfied_review_gates(tmp_path):
    client, csrf = client_for(tmp_path)
    response = client.get("/approvals", headers=ADMIN)
    assert response.status_code == 200
    assert b"Outstanding V2 requirements" in response.data
    assert b"DEPENDENCY_AUDIT_REMEDIATION" in response.data
    assert b"DB_MAINTENANCE_APPROVAL_AND_RESTORE" in response.data
    assert b"Approval is not execution permission" in response.data


def test_review_decision_does_not_clear_static_deployment_gates(tmp_path):
    client, csrf = client_for(tmp_path)
    ident = create_request(
        tmp_path / "review.sqlite3",
        application="example", action="deploy",
        scope="review-only staging approval", source_sha=SHA,
        reason="Synthetic proof of review state separation")
    response = client.post(f"/approvals/{ident}/decision", headers=ADMIN,
                           data={**csrf, "decision": "approved",
                                 "reason": "Review record only, not activation"})
    assert response.status_code == 302
    html = client.get("/approvals", headers=ADMIN).data
    assert b"DEPENDENCY_AUDIT_REMEDIATION" in html
    assert b"LEGACY_UNDERSCORE_ROUTE" in html


def test_legacy_registered_name_with_underscore_can_be_reviewed(tmp_path):
    ident = create_request(
        tmp_path / "approvals.sqlite3", application="Bank_of_mum",
        action="database-migration", scope="read-only migration design review",
        source_sha=SHA, reason="Required independent migration approval")
    requests, events = overview(tmp_path / "approvals.sqlite3")
    assert requests[0]["id"] == ident
    assert requests[0]["application"] == "Bank_of_mum"
    assert len(events) == 1


def test_special_design_only_requirements_are_visible(tmp_path):
    from tools.v2_design_holds import DESIGN_ONLY_HOLDS
    assert len(DESIGN_ONLY_HOLDS) == 6
    assert len({entry["application"] for entry in DESIGN_ONLY_HOLDS}) == 6
    client, _ = client_for(tmp_path)
    page = client.get("/approvals", headers=ADMIN)
    assert page.status_code == 200
    assert b"Special design-only holds (6)" in page.data
    for entry in DESIGN_ONLY_HOLDS:
        assert entry["application"].encode() in page.data
        for gate in entry["gates"]:
            assert gate.encode() in page.data


def test_concurrent_approval_only_one_transition_commits(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store = tmp_path / "approvals.sqlite3"
    ident = create_request(
        store, application="example", action="service-change",
        scope="isolated service review", source_sha=SHA,
        reason="Concurrency proof without any real executor")

    def approve(_):
        try:
            decide(store, ident, decision="approved",
                   reason="Concurrent review approval attempt")
            return True
        except ApprovalError:
            return False

    with ThreadPoolExecutor(max_workers=5) as pool:
        outcomes = list(pool.map(approve, range(5)))
    assert sum(outcomes) == 1
    assert [event["event"] for event in overview(store)[1]].count("approved") == 1


def test_group_readable_approval_store_is_rejected(tmp_path):
    store = tmp_path / "approvals.sqlite3"
    create_request(
        store, application="example", action="proxy-route",
        scope="read-only route review", source_sha=SHA,
        reason="Check storage confidentiality restrictions")
    store.chmod(0o644)
    with pytest.raises(ApprovalError, match="private"):
        overview(store)
