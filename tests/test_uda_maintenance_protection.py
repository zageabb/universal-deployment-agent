from datetime import datetime, timezone, timedelta
import os
import socket
import pytest
from tools import uda_maintenance_protection as p
from tools.uda_production_release_plan import digest


class Session:
    def __init__(self, plan):
        self.record = {"phase": "prepared", "plan": plan}
    def load(self):
        return self.record
    def save(self, record):
        self.record = record


@pytest.fixture
def lab(tmp_path):
    now = datetime.now(timezone.utc)
    body = {"host": socket.gethostname(), "uid": os.getuid(), "revision": "fixture"}
    plan = {"contract": body, "sha256": digest(body), "status": "PLAN_ONLY",
            "production_upgrade_authorized": False}
    evidence = {"version": 1, "decision": "APPROVE_UDA_V2_INSTALL",
                "contract_sha256": plan["sha256"], **body, "operator": "fixture",
                "not_before": (now - timedelta(minutes=1)).isoformat(),
                "expires_at": (now + timedelta(minutes=1)).isoformat()}
    runtime = tmp_path / ".local/share/deployment-agent"
    target = runtime / "sci-next-releases" / "release"
    target.mkdir(parents=True)
    (runtime / "sci-next-current").symlink_to(target)
    return Session(plan), evidence, now, tmp_path, target


def test_expiry_rollback_only(lab):
    s, e, now, _, _ = lab
    p.bind(s, e, now=now)
    assert p.authorize(s, now=now)
    s.record["phase"] = "applying"
    expired = now + timedelta(minutes=2)
    with pytest.raises(ValueError, match="outside valid window"):
        p.authorize(s, now=expired)
    assert p.authorize(s, recovery=True, now=expired)


@pytest.mark.parametrize("phase", ["prepared", "accepted", "rolled_back", "aborted"])
def test_no_recovery_terminal_or_prepared(lab, phase):
    s, e, now, _, _ = lab
    p.bind(s, e, now=now)
    s.record["phase"] = phase
    with pytest.raises(ValueError, match="Rollback-only"):
        p.authorize(s, recovery=True, now=now)


def test_approval_tampering(lab):
    s, e, now, _, _ = lab
    p.bind(s, e, now=now)
    s.record["maintenance_approval"]["evidence"]["operator"] = "changed"
    with pytest.raises(ValueError, match="receipt mismatch"):
        p.authorize(s, now=now)


def test_pointer_drift(lab):
    s, e, now, home, target = lab
    before = p.application_pointer(home)
    other = target.parent / "other"
    other.mkdir()
    pointer = target.parent.parent / "sci-next-current"
    pointer.unlink()
    pointer.symlink_to(other)
    with pytest.raises(ValueError, match="boundary drift"):
        p.verify_application_pointer(home, before)


@pytest.mark.parametrize("writer,app", [(False, True), (True, False), (True, True)])
def test_independent_protection(lab, writer, app):
    s, e, now, home, target = lab
    pointer = p.application_pointer(home)
    args = (s, home, pointer, lambda: writer, lambda *a: app)
    if writer and app:
        assert p.protection(*args)
    else:
        with pytest.raises(ValueError, match="Independent"):
            p.protection(*args)
