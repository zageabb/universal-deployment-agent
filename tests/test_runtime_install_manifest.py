"""Ensure the non-Git UDA runtime installer includes source dashboard dependencies.

Static regression only. NEVER executes install.sh or touches systemd/host files.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def installer_assets() -> set[str]:
    script = (ROOT / "install.sh").read_text()
    # Only inspect explicit literal installer references. This does not invoke
    # shell commands or infer production state.
    direct = set(re.findall(r'\$SOURCE_DIR/([A-Za-z0-9_./-]+)', script))
    module_block = script.split("for module in ", 1)[1].split("\ndo\n", 1)[0]
    modules = set(re.findall(r'[A-Za-z0-9_]+\.py', module_block))
    return direct | modules


def test_installer_copies_all_dashboard_and_agent_local_imports():
    assets = installer_assets()
    for name in ("dashboard.py", "deploy_agent.py"):
        tree = ast.parse((ROOT / name).read_text())
        for stmt in ast.walk(tree):
            if isinstance(stmt, ast.ImportFrom) and stmt.module:
                module = stmt.module.split(".", 1)[0]
                if (ROOT / (module + ".py")).is_file():
                    assert module + ".py" in assets, (name, module)
            elif isinstance(stmt, ast.Import):
                for part in stmt.names:
                    module = part.name.split(".", 1)[0]
                    if (ROOT / (module + ".py")).is_file():
                        assert module + ".py" in assets, (name, module)


def test_installer_includes_approval_and_v2_schema_assets():
    assets = installer_assets()
    required = {
        "approval_centre.py", "approval_identity.py",
        "deployment_reporting.py", "onboarding_v2.py",
        "onboarding_v2_approval.py", "uda_manifest_v2_validate.py",
        "templates/approvals.html", "templates/onboarding.html",
        "schemas/uda-manifest-v1.schema.json",
        "schemas/uda-manifest-v2.schema.json",
    }
    assert required <= assets


def test_installer_does_not_overwrite_existing_protected_config():
    script = (ROOT / "install.sh").read_text()
    assert 'if [ ! -f "$CONFIG_DIR/config.json" ]; then' in script
    assert 'install -m 0600 "$SOURCE_DIR/config.example.json" "$CONFIG_DIR/config.json"' in script


def test_installer_creates_templates_directory_before_copying_views():
    script = (ROOT / "install.sh").read_text()
    assert script.index('mkdir -p "$DATA_DIR/templates"') < script.index(
        'install -m 0644 "$SOURCE_DIR/templates/onboarding.html"')
