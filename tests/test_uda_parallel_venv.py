import pytest
from tools import uda_parallel_venv as v


@pytest.fixture
def lab(tmp_path):
    root = tmp_path / "uda-venv-lab-test"
    root.mkdir(mode=0o700)
    live, old, new = v.layout(root)
    for path, marker in ((live, "old"), (new, "new")):
        path.mkdir()
        (path / ".uda-fixture").write_text(marker)
    return root


def test_switch_restore(lab):
    v.switch(lab)
    assert v.state(lab) == ("candidate_link", "old", "new")
    v.restore(lab)
    assert v.state(lab) == ("old", "absent", "new")
    v.restore(lab)
    assert v.state(lab) == ("old", "absent", "new")


@pytest.mark.parametrize("boundary", ["after_rename", "after_link"])
def test_interrupted_switch(lab, boundary):
    def interrupt(point):
        if point == boundary:
            raise RuntimeError("interrupted")
    with pytest.raises(RuntimeError, match="interrupted"):
        v.switch(lab, interrupt=interrupt)
    v.restore(lab)
    assert v.state(lab) == ("old", "absent", "new")


def test_unexpected_link_refused(lab):
    v.switch(lab)
    live, _, _ = v.layout(lab)
    live.unlink()
    live.symlink_to("/tmp")
    with pytest.raises(ValueError, match="Unexpected symlink"):
        v.restore(lab)


def test_existing_retained_environment_refused(lab):
    _, old, _ = v.layout(lab)
    old.mkdir()
    (old / ".uda-fixture").write_text("old")
    with pytest.raises(ValueError, match="initial layout"):
        v.switch(lab)


def test_non_disposable_root_refused(tmp_path):
    with pytest.raises(ValueError, match="Private disposable"):
        v.switch(tmp_path)
