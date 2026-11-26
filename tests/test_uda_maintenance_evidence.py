from datetime import datetime, timedelta, timezone
import hashlib
import os
import socket
import pytest
from tools import uda_maintenance_evidence as m
from tools.uda_production_release_plan import digest

NOW = datetime(2026, 11, 26, 15, tzinfo=timezone.utc)


def fixture():
    body = {"host": socket.gethostname(), "uid": os.getuid(), "revision": "fixture"}
    plan = {"contract": body, "sha256": digest(body), "status": "PLAN_ONLY", "production_upgrade_authorized": False}
    evidence = {"version": 1, "decision": "APPROVE_UDA_V2_INSTALL",
                "contract_sha256": plan["sha256"], **body, "operator": "fixture",
                "not_before": (NOW - timedelta(minutes=15)).isoformat(),
                "expires_at": (NOW + timedelta(hours=1)).isoformat()}
    return plan, evidence


def test_approval():
    p, e = fixture()
    assert m.approval(p, e, now=NOW)["approval_sha256"] == digest(e)


@pytest.mark.parametrize("key,value", [("decision", "REVIEW"), ("contract_sha256", "wrong"),
    ("host", "wrong"), ("uid", -1), ("revision", "wrong"), ("operator", "")])
def test_approval_refusal(key, value):
    p, e = fixture()
    e[key] = value
    with pytest.raises(ValueError):
        m.approval(p, e, now=NOW)


def test_expired():
    p, e = fixture()
    with pytest.raises(ValueError, match="window"):
        m.approval(p, e, now=NOW + timedelta(hours=2))


def backup(tmp_path):
    tmp_path.chmod(0o700)
    p, _ = fixture()
    path = tmp_path / "backup.tar"
    path.write_bytes(b"fixture archive bytes")
    path.chmod(0o600)
    e = {"version": 1, "contract_sha256": p["sha256"], "archive": str(path),
         "archive_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size,
         "started_at": (NOW - timedelta(minutes=5)).isoformat(),
         "completed_at": (NOW - timedelta(minutes=1)).isoformat()}
    return p, e, path


def test_backup_bytes(tmp_path):
    p, e, _ = backup(tmp_path)
    result = m.backup_evidence(p, e, isolated_at=NOW - timedelta(minutes=10), now=NOW)
    assert result["archive_bytes_verified"] is True
    assert result["backup_completeness_verified"] is False


def test_backup_before_isolation(tmp_path):
    p, e, _ = backup(tmp_path)
    with pytest.raises(ValueError, match="after isolation"):
        m.backup_evidence(p, e, isolated_at=NOW - timedelta(minutes=2), now=NOW)


def test_backup_tamper(tmp_path):
    p, e, path = backup(tmp_path)
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        m.backup_evidence(p, e, isolated_at=NOW - timedelta(minutes=10), now=NOW)


def test_backup_symlink(tmp_path):
    p, e, path = backup(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(path)
    e["archive"] = str(link)
    with pytest.raises(OSError):
        m.backup_evidence(p, e, isolated_at=NOW - timedelta(minutes=10), now=NOW)
