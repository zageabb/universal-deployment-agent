"""Read-only boundary review, not an authorization or writer exclusion gate."""
from pathlib import Path
from tools.uda_production_backup_scope import scope
from tools.uda_runtime_integrity import payload_paths, ROOT
from tools.uda_production_admission import directory_review
from tools.v2_systemd_restore_rehearsal import UNIT_FILES, OVERRIDES, ENABLED
from tools.uda_production_payload_transaction import file_identity, parents


def review(home, *, source=ROOT, reviewed_application_dirs=()):
    roots = scope(home)
    runtime = roots["runtime"]
    # Exclusions require an explicit review, not a suffix or process-name rule.
    exclusions = set(reviewed_application_dirs)
    for name in exclusions:
        if name != "sci-next-releases":
            raise ValueError("Unreviewed application boundary: " + name)
        directory_review(runtime / name)
    payload = payload_paths(source)
    protected = set()
    for name in payload:
        if name.startswith("runtime/"):
            protected.add(Path(name).parts[1])
    protected.update({"venv", "venv-v2"})
    if exclusions & protected:
        raise ValueError("Application boundary overlaps installer payload")
    unknown = sorted(p.name for p in runtime.iterdir()
                     if p.name not in protected | exclusions)
    units = home / ".config/systemd/user"
    binary = home / ".local/bin"
    assets = {}
    for root, label, names in ((units, "systemd-user", (*UNIT_FILES, *OVERRIDES)),
                               (binary, "bin", ("uda-trigger-ci",))):
        for name in names:
            parents(root, name)
            identity = file_identity(root, name)
            if identity is None:
                raise ValueError("Missing rollback asset: " + name)
            assets[label + "/" + name] = identity
    links = {}
    for name, unit in ENABLED.items():
        parents(units, name)
        path = units / name
        if not path.is_symlink() or path.resolve(strict=True) != units / unit:
            raise ValueError("Unexpected enablement link: " + name)
        links[name] = str(path.readlink())
    return {"status": "REVIEW" if unknown or exclusions else "DISCOVERY_PASS",
            "runtime_unclassified": unknown,
            "proposed_application_exclusions": sorted(exclusions),
            "protected_runtime_entries": sorted(protected),
            "rollback_assets": assets, "enablement_links": links,
            "backup_scope_complete": False, "writer_exclusion_verified": False,
            "production_upgrade_authorized": False}
