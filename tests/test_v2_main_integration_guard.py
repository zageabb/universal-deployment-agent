"""Integration gate: UDA V2 must not become a host activation endpoint.

This explicitly scopes the check to *V2 code paths*. Existing v1 UDA
dashboard routes can already invoke deployment-agent and systemctl --user;
their privileges must be reviewed separately before merging into main.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re

from onboarding_worker_policy import worker_capabilities
from onboarding_v2_multiservice import simulate_multiservice_release

ROOT = Path(__file__).resolve().parents[1]


def _read(module):
    return (ROOT / module).read_text()


def _imports(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(part.name for part in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_dashboard_exposes_v2_preview_but_not_privileged_v2_worker():
    tree = ast.parse(_read("dashboard.py"))
    modules = _imports(tree)
    assert "onboarding_v2" in modules
    assert not any(name.startswith((
        "onboarding_v2_worker_rehearsal",
        "onboarding_v2_multiservice",
        "onboarding_v2_recovery_preflight",
        "onboarding_v2_recovery_journal",
        "onboarding_v2_unit_sandbox",
    )) for name in modules)
    functions = {n.name: n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "onboarding_preview" in functions
    preview = ast.unparse(functions["onboarding_preview"])
    assert "preview_v2(" in preview
    assert "rehearse_reviewed_release(" not in preview
    # A route cannot quietly grow a new V2 activation endpoint.
    routes = [
        (arg.value if isinstance(arg, ast.Constant) else "")
        for f in functions.values()
        for d in f.decorator_list
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
        and d.func.attr in ("get", "post", "put", "patch", "delete", "route")
        for arg in d.args[:1]
    ]
    assert routes
    assert not any(
        "v2" in path and re.search(r"install|execute|activate|recover|rollback|deploy", path)
        for path in routes
    )


def test_v2_adapters_are_offline_and_no_systemctl_dispatch():
    modules = [
        "onboarding_v2_multiservice.py",
        "onboarding_v2_worker_rehearsal.py",
        "onboarding_v2_unit_sandbox.py",
        "onboarding_v2_recovery_preflight.py",
        "onboarding_v2_recovery_journal.py",
        "onboarding_v2_approval.py",
    ]
    forbidden_modules = {"subprocess", "pty", "paramiko", "fabric"}
    for path in modules:
        tree = ast.parse(_read(path))
        assert not (_imports(tree) & forbidden_modules), path
        assert not any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"system", "popen", "execv", "execve", "spawnv"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
            for node in ast.walk(tree)
        ), path


def test_v2_rehearsal_and_recovery_are_explicitly_nonactivating():
    worker = ast.parse(_read("onboarding_v2_worker_rehearsal.py"))
    funcs = {n.name: n for n in ast.walk(worker)
             if isinstance(n, ast.FunctionDef)}
    source = ast.unparse(funcs["rehearse_reviewed_release"])
    assert "rehearsal_only is not True" in source
    assert "'production_activation_allowed': False" in source
    assert "'host_changes_allowed': False" in source
    recovery = ast.parse(_read("onboarding_v2_recovery_preflight.py"))
    recovery_func = next(n for n in ast.walk(recovery)
                         if isinstance(n, ast.FunctionDef)
                         and n.name == "plan_interrupted_recovery")
    content = ast.unparse(recovery_func)
    assert "'automatic_replay_allowed': False" in content
    assert "'can_execute': False" in content
    assert callable(simulate_multiservice_release)
    policy = worker_capabilities({"manual_recovery_requested": True,
                                  "production_activation": True,
                                  "automatic_crash_recovery": True})
    assert policy["production_activation"] is False
    assert policy["automatic_crash_recovery"] is False
    assert policy["worker_integration"] == "not_installed"


def test_docker_acceptance_remains_ci_only_and_networkless():
    workflow = _read(".github/workflows/v2-systemd-crash-acceptance.yml")
    assert "runs-on: ubuntu-latest" in workflow
    assert "--network none" in workflow
    assert "docker rm -f" in workflow
    assert "retention-days: 7" in workflow
    assert "ssh " not in workflow
    guard = _read("tests/integration/v2_systemd/crash_acceptance.py")
    assert 'UDA_V2_DISPOSABLE_CONTAINER' in guard
    assert 'Path("/.dockerenv")' in guard
    assert 'Path("/proc/1/comm")' in guard
    assert "production_activation_allowed" in guard


def test_review_only_tickets_cannot_be_promoted_to_worker_permission():
    source = ast.parse(_read("onboarding_v2_approval.py"))
    funcs = [n for n in ast.walk(source) if isinstance(n, ast.FunctionDef)]
    text = "\n".join(ast.unparse(n) for n in funcs)
    assert "'review_only'" in text
    assert "'can_install': False" in text
    policy = _read("onboarding_worker_policy.py")
    assert '"permission": "review_only"' in policy
    assert '"can_execute": False' in policy
