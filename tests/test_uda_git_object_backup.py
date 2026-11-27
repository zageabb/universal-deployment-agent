import os
import tarfile
import pytest
from tools.uda_backup_inventory import capture, write_selected, verify_snapshot


def test_reviewed_git_hardlinks(tmp_path):
    runtime = tmp_path / "runtime"
    suffix = "objects/0b/" + "a" * 38
    publisher = runtime / "publishers/lucky-lab/.git" / suffix
    remote = runtime / "remotes/lucky-lab.git" / suffix
    for p in (publisher, remote):
        p.parent.mkdir(parents=True)
    publisher.write_bytes(b"fixture Git object")
    os.link(publisher, remote)
    roots = {"runtime": runtime}
    expected = capture(roots)
    assert expected["runtime/publishers/lucky-lab/.git/" + suffix]["source_link_count"] == 2
    archive = tmp_path / "backup.tar"
    with tarfile.open(archive, "w", dereference=False) as tar:
        write_selected(tar, roots, expected)
    with tarfile.open(archive) as tar:
        assert tar.getmember("runtime/publishers/lucky-lab/.git/" + suffix).isfile()
        assert tar.getmember("runtime/remotes/lucky-lab.git/" + suffix).isfile()
    assert verify_snapshot(archive, roots, expected)["status"] == "INVENTORY_PASS"


def test_unreviewed_git_hardlink_refused(tmp_path):
    root = tmp_path / "runtime"
    path = root / "publishers/unknown/.git/objects/0b" / ("a" * 38)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"fixture")
    os.link(path, root / "alias")
    with pytest.raises(ValueError, match="Unsupported backup source"):
        capture({"runtime": root})


def test_external_alias_change_detected(tmp_path):
    root = tmp_path / "runtime"
    path = root / "publishers/lucky-lab/.git/objects/0b" / ("a" * 38)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"fixture")
    alias = tmp_path / "external"
    os.link(path, alias)
    roots = {"runtime": root}
    before = capture(roots)
    archive = tmp_path / "backup.tar"
    with tarfile.open(archive, "w", dereference=False) as tar:
        write_selected(tar, roots, before)
    alias.write_bytes(b"modified")
    with pytest.raises(ValueError, match="source inventory drift"):
        verify_snapshot(archive, roots, before)
