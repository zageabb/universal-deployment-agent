"""Read-only Approval Centre storage preflight fixture tests."""
from __future__ import annotations

import sqlite3

import pytest

from approval_centre import create_request
from tools.approval_store_preflight import inspect_store, main

SHA = "a" * 40


def store_fixture(tmp_path):
    store = tmp_path / "approvals.sqlite3"
    create_request(
        store, application="example", action="deploy",
        scope="disposable preflight test only", source_sha=SHA,
        reason="Isolated read-only storage fixture test")
    return store


def test_existing_private_store_passes_without_mutating_contents(tmp_path):
    store = store_fixture(tmp_path)
    before = store.read_bytes()
    result = inspect_store(store)
    assert result["result"] == "PASS"
    assert result["sqlite_quick_check"] == "ok"
    assert result["read_only_check"] is True
    assert result["requests_or_audit_contents_exported"] is False
    assert store.read_bytes() == before


def test_missing_store_does_not_get_created(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    assert main(["--store", str(missing)]) == 1
    assert not missing.exists()


def test_public_permissions_are_rejected(tmp_path):
    store = store_fixture(tmp_path)
    store.chmod(0o644)
    with pytest.raises(ValueError, match="group/world"):
        inspect_store(store)


def test_symlink_rejected(tmp_path):
    store = store_fixture(tmp_path)
    link = tmp_path / "linked.sqlite3"
    link.symlink_to(store)
    with pytest.raises(ValueError, match="symbolic links"):
        inspect_store(link)


def test_missing_audit_trigger_rejected(tmp_path):
    store = store_fixture(tmp_path)
    with sqlite3.connect(store) as conn:
        conn.execute("DROP TRIGGER audit_no_delete")
    with pytest.raises(ValueError, match="triggers"):
        inspect_store(store)


def test_uninitialized_private_sqlite_rejected(tmp_path):
    store = tmp_path / "empty.sqlite3"
    with sqlite3.connect(store):
        pass
    store.chmod(0o600)
    with pytest.raises(ValueError, match="tables"):
        inspect_store(store)
