import hashlib
import io
import tarfile
import pytest
from tools.uda_backup_coverage import verify


def make(tmp_path, members):
    path = tmp_path / "backup.tar"
    with tarfile.open(path, "w") as tar:
        for name, data, mode in members:
            item = tarfile.TarInfo(name)
            item.mode = mode
            item.size = len(data)
            tar.addfile(item, io.BytesIO(data))
    return path


def expected():
    return {"runtime/file": {"size": 3, "mode": 0o600,
                             "sha256": hashlib.sha256(b"old").hexdigest()}}


def test_exact_coverage(tmp_path):
    p = make(tmp_path, [("runtime/file", b"old", 0o600)])
    assert verify(p, expected())["verified_files"] == 1


@pytest.mark.parametrize("members,message", [
    ([], "Missing"),
    ([("runtime/file", b"bad", 0o600)], "content mismatch"),
    ([("runtime/file", b"old", 0o644)], "metadata mismatch"),
    ([("runtime/file", b"old", 0o600)] * 2, "Duplicate"),
    ([("../escape", b"old", 0o600)], "Unsafe"),
    ([("unreviewed", b"old", 0o600)], "Unexpected"),
])
def test_refusal(tmp_path, members, message):
    with pytest.raises(ValueError, match=message):
        verify(make(tmp_path, members), expected())


def test_symlink_refused(tmp_path):
    path = tmp_path / "backup.tar"
    with tarfile.open(path, "w") as tar:
        item = tarfile.TarInfo("runtime/file")
        item.type = tarfile.SYMTYPE
        item.linkname = "/etc/passwd"
        tar.addfile(item)
    with pytest.raises(ValueError, match="Unsupported"):
        verify(path, expected())
