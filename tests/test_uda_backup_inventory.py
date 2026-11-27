import sqlite3
import tarfile
import pytest
from tools import uda_backup_inventory as b


def fixture(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "empty").mkdir()
    (root / "file").write_bytes(b"original")
    (root / "link").symlink_to("file")
    with sqlite3.connect(root / "identity.db") as db:
        db.execute("CREATE TABLE fixture (id INTEGER)")
        db.execute("INSERT INTO fixture VALUES (1)")
    roots = {"runtime": root}
    expected = b.capture(roots)
    archive = tmp_path / "backup.tar"
    with tarfile.open(archive, "w", dereference=False) as tar:
        tar.add(root, arcname="runtime")
    return root, roots, expected, archive


def test_complete_inventory(tmp_path):
    root, roots, expected, archive = fixture(tmp_path)
    result = b.verify_snapshot(archive, roots, expected, ["runtime/identity.db"])
    assert result["entries"] == 5
    assert result["sqlite_checked"] == ["runtime/identity.db"]
    assert result["application_consistency_verified"] is False


def test_source_drift(tmp_path):
    root, roots, expected, archive = fixture(tmp_path)
    (root / "file").write_bytes(b"changed")
    with pytest.raises(ValueError, match="source inventory drift"):
        b.verify_snapshot(archive, roots, expected)


def test_link_metadata(tmp_path):
    _, _, expected, archive = fixture(tmp_path)
    expected["runtime/link"]["target"] = "other"
    with pytest.raises(ValueError, match="link mismatch"):
        b.verify(archive, expected)


def test_directory_metadata(tmp_path):
    _, _, expected, archive = fixture(tmp_path)
    expected["runtime/empty"]["mode"] ^= 0o100
    with pytest.raises(ValueError, match="metadata mismatch"):
        b.verify(archive, expected)


def test_missing_member(tmp_path):
    _, _, expected, archive = fixture(tmp_path)
    expected["runtime/missing"] = expected["runtime/file"]
    with pytest.raises(ValueError, match="Missing archive members"):
        b.verify(archive, expected)


def test_sidecar_refusal(tmp_path):
    _, _, expected, archive = fixture(tmp_path)
    expected["runtime/identity.db-wal"] = expected["runtime/file"]
    with pytest.raises(ValueError, match="not standalone"):
        b.verify(archive, expected, ["runtime/identity.db"])


def test_corrupt_sqlite(tmp_path):
    p = tmp_path / "corrupt.db"
    p.write_bytes(b"not a database" * 100)
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        b.sqlite_check(p)


def test_hardlink_refusal(tmp_path):
    import os
    root = tmp_path / "source"
    root.mkdir()
    (root / "file").write_bytes(b"original")
    os.link(root / "file", root / "duplicate")
    with pytest.raises(ValueError, match="Unsupported backup source"):
        b.capture({"runtime": root})
