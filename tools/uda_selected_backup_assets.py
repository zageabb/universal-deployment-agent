"""Reviewed backup selection, not a live installation gate."""
from pathlib import Path
from tools.uda_reviewed_backup_boundaries import review
from tools.uda_production_backup_scope import scope
from tools.v2_systemd_restore_rehearsal import UNIT_FILES, OVERRIDES, ENABLED
from tools.uda_backup_inventory import capture

CLASSIFIED = frozenset({
    "__pycache__", "backups", "deploy_should_cost_intelligence_next.py",
    "deploy_should_cost_intelligence_next.py.before-npm-ci-20261027",
    "home.py.before-login-redirect-20261112T174000Z", "ingress-test",
    "proxy_config.py.before-login-redirect-20261112T174000Z",
    "proxy_config.py.before-screencraft-uda-20261112T171100Z",
    "publishers", "remotes", "sci-next-current", "shadowprompt_lab_wsgi.py",
})


def selection(home):
    report = review(home, reviewed_application_dirs=["sci-next-releases"])
    unknown = set(report["runtime_unclassified"]) - CLASSIFIED
    if unknown:
        raise ValueError("Unclassified runtime entries: " + ", ".join(sorted(unknown)))
    roots = scope(home)
    runtime = roots["runtime"]
    pointer = runtime / "sci-next-current"
    releases = runtime / "sci-next-releases"
    if not pointer.is_symlink() or not pointer.resolve(strict=True).is_dir() or pointer.resolve().parent != releases.resolve():
        raise ValueError("Unexpected SCI Next active release pointer")
    roots.update({"systemd-user": home / ".config/systemd/user",
                  "bin": home / ".local/bin"})
    selected = {"systemd-user": set(UNIT_FILES) | {Path(n).parts[0] for n in (*OVERRIDES, *ENABLED)},
                "bin": {"uda-trigger-ci"}}
    for name in (*OVERRIDES, *ENABLED):
        p = Path(name)
        selected.setdefault("systemd-user/" + p.parts[0], set()).add(p.name)
    excluded = ("runtime/sci-next-releases",)
    return roots, selected, excluded


def inspect(home):
    roots, selected, excluded = selection(home)
    inventory = capture(roots, selected=selected, excluded=excluded)
    required = {"systemd-user/" + n for n in (*UNIT_FILES, *OVERRIDES, *ENABLED)} | {"bin/uda-trigger-ci", "runtime/sci-next-current"}
    if not required <= set(inventory):
        raise ValueError("Selected backup assets missing")
    return {"status": "SELECTED_SCOPE_REVIEW", "entries": len(inventory),
            "rollback_assets_present": len(required) - 1,
            "excluded_application_tree": list(excluded),
            "active_pointer_preserved": True,
            "backup_scope_complete": False, "writer_exclusion_verified": False,
            "production_upgrade_authorized": False}
