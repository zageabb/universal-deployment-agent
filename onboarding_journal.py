"""Durable, append-only activation event journal.

Contains only transaction ID, state, operation names and sanitized exception
descriptions. Never log environment files, GitHub tokens or app secrets.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

from onboarding import OnboardingError

ID = re.compile(r"^[a-f0-9-]{36}$")
PERMITTED = {"transaction_id", "state", "executed", "rolled_back", "error", "rollback_errors"}
MAX_LOG_BYTES = 5 * 1024 * 1024


class FileJournal:
    def __init__(self, root: Path, transaction_id: str):
        if not isinstance(transaction_id, str) or not ID.fullmatch(transaction_id):
            raise OnboardingError("Invalid transaction journal identifier")
        if root.expanduser().is_symlink():
            raise OnboardingError("Journal root cannot be a symlink")
        directory = root.expanduser()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.stat().st_mode & 0o077:
            raise OnboardingError("Journal root must be private")
        self.path = directory / (transaction_id + ".jsonl")
        if self.path.is_symlink():
            raise OnboardingError("Journal path cannot be a symlink")
        self.transaction_id = transaction_id

    def __call__(self, record: dict) -> None:
        if record.get("transaction_id") != self.transaction_id:
            raise OnboardingError("Audit journal transaction mismatch")
        if set(record) - PERMITTED:
            raise OnboardingError("Unexpected journal fields")
        # No exception text is guaranteed secret-free; redact before persistence.
        sanitized = dict(record)
        for key in ("error",):
            if sanitized.get(key):
                sanitized[key] = "[error; consult protected service logs]"
        sanitized["rollback_errors"] = [
            "[rollback error; consult protected service logs]"
            for _ in sanitized.get("rollback_errors", [])
        ]
        line = (json.dumps(sanitized, sort_keys=True, separators=(",", ":")) + "\n").encode()
        if len(line) > 32_768:
            raise OnboardingError("Journal event too large")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        try:
            with os.fdopen(fd, "ab", closefd=False) as handle:
                if os.fstat(fd).st_size + len(line) > MAX_LOG_BYTES:
                    raise OnboardingError("Journal size limit exceeded")
                handle.write(line)
                handle.flush()
                os.fsync(fd)
        finally:
            os.close(fd)

    def events(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
