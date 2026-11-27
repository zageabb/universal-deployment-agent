import pytest
from tools import uda_production_integrity_gates as g
from tools.uda_production_release_plan import digest
from tools.uda_controlled_activation import UNITS
from test_uda_production_service_isolation import Adapter, baseline
from tools.uda_controlled_activation import TIMERS, WEB


def test_environment_drift(tmp_path):
    tmp_path.chmod(0o700)
    p = tmp_path / "module.py"
    p.write_text("original")
    p.chmod(0o600)
    receipt = g.environment(tmp_path)
    assert g.verify_environment(tmp_path, receipt)
    p.write_text("changed")
    with pytest.raises(ValueError, match="drift"):
        g.verify_environment(tmp_path, receipt)


def test_environment_rename(tmp_path):
    root = tmp_path / "venv"
    root.mkdir(mode=0o700)
    p = root / "module"
    p.write_text("original")
    p.chmod(0o600)
    receipt = g.environment(root)
    retained = tmp_path / "retained"
    root.rename(retained)
    assert g.verify_environment(retained, receipt)


def test_environment_external_link(tmp_path):
    tmp_path.chmod(0o700)
    (tmp_path / "link").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="Unexpected environment link"):
        g.environment(tmp_path)


def test_environment_world_write(tmp_path):
    tmp_path.chmod(0o700)
    p = tmp_path / "module"
    p.write_text("original")
    p.chmod(0o666)
    with pytest.raises(ValueError, match="Unsafe environment file"):
        g.environment(tmp_path)


def test_preserved_files(tmp_path):
    runtime = tmp_path / ".local/share/deployment-agent"
    units = tmp_path / ".config/systemd/user"
    binary = tmp_path / ".local/bin"
    for p in (runtime, units, binary):
        p.mkdir(parents=True, mode=0o700)
    def write(root, name):
        p = root / name
        p.write_bytes(b"original")
        p.chmod(0o600)
        return {"status": "present", **g.file_identity(root, name)}
    body = {"preserved": {f"runtime/keep{i}": write(runtime, f"keep{i}") for i in range(21)},
            "units": {u: write(units, u) for u in UNITS}}
    plan = {"contract": body, "sha256": digest(body)}
    assert g.preserved(plan, tmp_path)
    (units / UNITS[0]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="Preserved file drift"):
        g.preserved(plan, tmp_path)


def test_units_idle():
    adapter = Adapter()
    with pytest.raises(ValueError, match="not isolated"):
        g.units_idle(adapter, baseline())
    for u in TIMERS + WEB:
        adapter.change("stop", u)
    assert g.units_idle(adapter, baseline())
