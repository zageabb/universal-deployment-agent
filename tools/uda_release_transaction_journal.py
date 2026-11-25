"""Persistent release journal primitives; no production mutation controller.

The caller must hold the lock for the entire transaction. This journal
records intent, not maintenance authorization. No systemctl calls.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
from tools.uda_install_journal import durable_write, sync_dir
from tools.uda_production_release_plan import digest

NEXT = {
    "prepared": {"isolating", "aborted"},
    "isolating": {"isolated", "recovering"},
    "isolated": {"applying", "recovering"},
    "applying": {"switching", "recovering"},
    "switching": {"health", "recovering"},
    "health": {"accepted", "recovering"},
    "recovering": {"rolled_back", "review"},
    "review": {"recovering"},
    "accepted": set(), "rolled_back": set(), "aborted": set(),
}


def private(root):
    s = root.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o700:
        raise ValueError("Journal directory must be owner-private")
    if any(k.startswith("system.posix_acl_") for k in os.listxattr(root, follow_symlinks=False)):
        raise ValueError("Journal ACL refused")


def safe_file(fd):
    s = os.fstat(fd)
    if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_nlink != 1 or stat.S_IMODE(s.st_mode) != 0o600:
        raise ValueError("Unsafe journal file")


@contextmanager
def locked(root):
    private(root)
    fd = os.open(root / "release.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        safe_file(fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sync_dir(root)
        session = Session(root)
        try:
            yield session
        finally:
            session.closed = True
    finally:
        os.close(fd)


class Session:
    def __init__(self, root):
        self.root = root
        self.path = root / "transaction.json"
        self.closed = False

    def check(self):
        if self.closed:
            raise ValueError("Journal session closed")
        private(self.root)

    def load(self):
        self.check()
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            safe_file(stream.fileno())
            record = json.load(stream)
        if record["sha256"] != digest(record["body"]):
            raise ValueError("Journal digest mismatch")
        body = record["body"]
        if body["version"] != 1 or body["phase"] not in NEXT:
            raise ValueError("Unknown journal state")
        return body

    def save(self, body):
        self.check()
        durable_write(self.path, json.dumps({"body": body, "sha256": digest(body)}, sort_keys=True).encode())

    def begin(self, plan):
        self.check()
        if self.path.exists() or self.path.is_symlink():
            raise ValueError("Existing transaction requires review")
        if plan.get("status") != "PLAN_ONLY" or plan.get("production_upgrade_authorized") is not False or digest(plan["contract"]) != plan["sha256"]:
            raise ValueError("Invalid release contract")
        if not plan["contract"]["venv"].get("receipt"):
            raise ValueError("Candidate receipt required")
        body = {"version": 1, "phase": "prepared", "sequence": 0,
                "plan": plan, "production_upgrade_authorized": False}
        self.save(body)
        return body

    def advance(self, phase):
        body = self.load()
        if phase not in NEXT[body["phase"]]:
            raise ValueError("Illegal transaction transition")
        body["phase"] = phase
        body["sequence"] += 1
        self.save(body)
        return body
