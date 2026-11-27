"""Read-only production scope and writer indicators; not enforced exclusion.

Do not stop processes or scan unrelated user file contents. The caller still
needs a maintenance guard that prevents new writers from starting.
"""
import json
import os
from pathlib import Path
from tools.uda_production_admission import directory_review


def scope(home):
    home = home.resolve(strict=True)
    for variable, expected in (("XDG_CONFIG_HOME", home / ".config"),
                               ("XDG_DATA_HOME", home / ".local/share"),
                               ("XDG_STATE_HOME", home / ".local/state")):
        if os.environ.get(variable) and Path(os.environ[variable]).resolve() != expected:
            raise ValueError("Nonstandard XDG scope: " + variable)
    roots = {"runtime": home / ".local/share/deployment-agent",
             "config": home / ".config/deployment-agent",
             "state": home / ".local/state/deployment-agent"}
    for path in roots.values():
        directory_review(path)
    config = roots["config"] / "config.json"
    if config.is_symlink() or not config.is_file():
        raise ValueError("Unsafe UDA config")
    cfg = json.loads(config.read_text())
    defaults = {"lock_file": roots["state"] / "deploy.lock",
                "log_file": roots["state"] / "deploy.log",
                "state_file": roots["state"] / "status.json",
                "identity_db": roots["state"] / "identity.db"}
    for key, default in defaults.items():
        raw = str(cfg.get(key, default))
        path = home / raw[2:] if raw.startswith("~/") else Path(raw)
        if not path.is_absolute() or not any(path.resolve().is_relative_to(root.resolve()) for root in roots.values()):
            raise ValueError("External configured state requires review: " + key)
    return roots


def within(value, roots):
    # procfs may append " (deleted)" to an open pathname.
    path = Path(value.removesuffix(" (deleted)"))
    return path.is_absolute() and any(path.is_relative_to(root) for root in roots)


def process_indicators(roots, proc=Path("/proc")):
    """Report same-UID processes with open descriptors or cwd/exe in scope.

    Conservative: even readers count. Permission failures on same-UID
    processes require review. No guarantee against other UIDs or future opens.
    """
    roots = tuple(p.resolve() for p in roots.values())
    findings = []
    for process in proc.iterdir():
        if not process.name.isdecimal() or int(process.name) == os.getpid():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            links = [process / "cwd", process / "exe"]
            links.extend((process / "fd").iterdir())
            for link in links:
                try:
                    target = os.readlink(link)
                except FileNotFoundError:
                    continue
                if within(target, roots):
                    findings.append({"pid": int(process.name), "indicator": link.name})
        except FileNotFoundError:
            continue
        except PermissionError:
            findings.append({"pid": int(process.name), "indicator": "uninspectable"})
    return {"status": "REVIEW" if findings else "NO_INDICATORS",
            "findings": findings, "writer_exclusion_verified": False,
            "production_upgrade_authorized": False}
