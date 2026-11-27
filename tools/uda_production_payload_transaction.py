"""Contract-bound payload mutation primitives, no executable live entry point.

Caller must hold the release journal lock, establish isolation, verify backup
and authorization. Only installer runtime paths can be mutated.
"""
from pathlib import Path
import hashlib
import os
from tools.uda_install_journal import durable_write, sync_dir
from tools.uda_production_admission import directory_review, REPLACEMENTS
from tools.uda_production_replacement_plan import inspect
from tools.uda_runtime_integrity import inventory, regular_file
from tools.uda_permanent_candidate_venv import identity
from tools.uda_candidate_admission import tree


def file_identity(root, relative):
    value = inspect(root, relative)
    if value["status"] == "missing":
        return None
    if value["status"] != "present":
        raise ValueError("Unsafe payload: " + relative)
    return {k: value[k] for k in ("sha256", "mode")}


def expected(value):
    return None if value is None else {k: value[k] for k in ("sha256", "mode")}


def entries(session, stage):
    record = session.load()
    contract = record["plan"]["contract"]
    items = contract["mutations"]
    manifest = inventory(stage)["files"]
    if len(items) != 41 or {n for n,e in items.items() if e["action"] == "replace"} != REPLACEMENTS:
        raise ValueError("Unexpected mutation scope")
    if set(items) & set(contract["preserved"]) or set(items) | set(contract["preserved"]) != set(manifest):
        raise ValueError("Incomplete payload scope")
    for name, entry in items.items():
        if not name.startswith("runtime/") or entry["new"] != manifest[name]:
            raise ValueError("Unexpected candidate payload")
        if entry["action"] not in {"add", "replace"} or (entry["old"] is None) != (entry["action"] == "add"):
            raise ValueError("Unexpected old identity")
    return record, items


def parents(root, relative, create=False):
    directory_review(root)
    p = root
    for part in Path(relative).parts[:-1]:
        if part in {"..", "."}:
            raise ValueError("Unsafe relative path")
        child = p / part
        if create and not child.exists() and not child.is_symlink():
            child.mkdir(mode=0o700)
            sync_dir(p)
        if not child.exists() and not child.is_symlink():
            return
        directory_review(child)
        p = child


def apply(session, stage, runtime, *, interrupt=lambda _: None):
    record, items = entries(session, stage)
    if record["phase"] != "isolated":
        raise ValueError("Isolated phase required")
    backup = session.root / "payload-backup"
    backup.mkdir(mode=0o700)
    sync_dir(session.root)
    for name, item in sorted(items.items()):
        rel = name.removeprefix("runtime/")
        parents(runtime, rel)
        if file_identity(runtime, rel) != expected(item["old"]):
            raise ValueError("Installed payload drift: " + name)
        if item["old"] is not None:
            data = (runtime / rel).read_bytes()
            if hashlib.sha256(data).hexdigest() != item["old"]["sha256"]:
                raise ValueError("Backup source drift")
            durable_write(backup / hashlib.sha256(name.encode()).hexdigest(), data)
    for name, item in items.items():
        if item["old"] is not None:
            key = hashlib.sha256(name.encode()).hexdigest()
            if file_identity(backup, key) != {"sha256": item["old"]["sha256"], "mode": 0o600}:
                raise ValueError("Backup verification failed")
    missing_dirs = set()
    for name in items:
        for parent in Path(name.removeprefix("runtime/")).parents:
            if parent == Path("."):
                continue
            p = runtime / parent
            if not p.exists() and not p.is_symlink():
                missing_dirs.add(str(parent))
    record["missing_payload_dirs"] = sorted(missing_dirs)
    record["payload_backup_ready"] = True
    session.save(record)
    session.advance("applying")
    for name, item in sorted(items.items()):
        rel = name.removeprefix("runtime/")
        parents(runtime, rel, create=True)
        if file_identity(runtime, rel) != expected(item["old"]):
            raise ValueError("Installed payload drift: " + name)
        data = regular_file(stage, name).read_bytes()
        if hashlib.sha256(data).hexdigest() != item["new"]["sha256"]:
            raise ValueError("Candidate payload drift")
        interrupt("before:" + name)
        durable_write(runtime / rel, data, item["new"]["mode"])
        interrupt("after:" + name)
    for name, item in items.items():
        if file_identity(runtime, name.removeprefix("runtime/")) != expected(item["new"]):
            raise ValueError("Applied payload mismatch")


def switch(session, runtime, *, interrupt=lambda _: None):
    record = session.load()
    if record["phase"] != "applying":
        raise ValueError("Applying phase required")
    directory_review(runtime)
    live, retained, candidate = (runtime / n for n in ("venv", "venv-v1-retained", "venv-v2"))
    receipt = record["plan"]["contract"]["venv"]["receipt"]
    if str(candidate) != receipt["candidate"] or list(identity(candidate)) != receipt["identity"] or tree(candidate) != receipt["tree_sha256"]:
        raise ValueError("Candidate environment drift")
    if retained.exists() or retained.is_symlink():
        raise ValueError("Retained environment already exists")
    from tools.uda_production_integrity_gates import verify_environment
    if "original_environment" in record:
        verify_environment(live, record["original_environment"])
    old = list(identity(live))
    record["old_venv_identity"] = old
    session.save(record)
    session.advance("switching")
    live.rename(retained)
    sync_dir(runtime)
    interrupt("after_rename")
    live.symlink_to("venv-v2")
    sync_dir(runtime)
    interrupt("after_link")
    if list(identity(retained)) != old or os.readlink(live) != "venv-v2":
        raise ValueError("Environment switch mismatch")
    session.advance("health")


def restore_environment(session, runtime):
    record = session.load()
    if record["phase"] != "recovering":
        raise ValueError("Recovery phase required")
    old = record.get("old_venv_identity")
    live, retained = runtime / "venv", runtime / "venv-v1-retained"
    directory_review(runtime)
    if old is None:
        if retained.exists() or retained.is_symlink() or live.is_symlink():
            raise ValueError("Unexpected environment layout")
        return
    if "original_environment" in record:
        from tools.uda_production_integrity_gates import verify_environment
        verify_environment(retained if retained.exists() or retained.is_symlink() else live, record["original_environment"])
    if live.is_symlink():
        if os.readlink(live) != "venv-v2" or list(identity(retained)) != old:
            raise ValueError("Unexpected switched environment")
        live.unlink()
        sync_dir(runtime)
    if retained.exists() or retained.is_symlink():
        if live.exists() or live.is_symlink() or list(identity(retained)) != old:
            raise ValueError("Unexpected retained environment")
        retained.rename(live)
        sync_dir(runtime)
    if list(identity(live)) != old:
        raise ValueError("Original environment mismatch")


def restore_files(session, stage, runtime):
    record, items = entries(session, stage)
    if record["phase"] != "recovering":
        raise ValueError("Recovery phase required")
    if not record.get("payload_backup_ready"):
        if any(file_identity(runtime, n.removeprefix("runtime/")) != expected(e["old"]) for n,e in items.items()):
            raise ValueError("Unprepared payload changed")
        return
    backup = session.root / "payload-backup"
    directory_review(backup)
    data = {}
    for name, item in items.items():
        rel = name.removeprefix("runtime/")
        parents(runtime, rel)
        if file_identity(runtime, rel) not in (expected(item["old"]), expected(item["new"])):
            raise ValueError("Unexpected runtime bytes: " + name)
        if item["old"] is not None:
            key = hashlib.sha256(name.encode()).hexdigest()
            if file_identity(backup, key) != {"sha256": item["old"]["sha256"], "mode": 0o600}:
                raise ValueError("Backup integrity failure")
            data[name] = (backup / key).read_bytes()
            if hashlib.sha256(data[name]).hexdigest() != item["old"]["sha256"]:
                raise ValueError("Backup drift")
    for name, item in sorted(items.items(), reverse=True):
        rel = name.removeprefix("runtime/")
        actual = file_identity(runtime, rel)
        if actual == expected(item["old"]):
            continue
        if actual != expected(item["new"]):
            raise ValueError("Runtime drift during recovery")
        if item["old"] is None:
            (runtime / rel).unlink()
            sync_dir((runtime / rel).parent)
        else:
            durable_write(runtime / rel, data[name], item["old"]["mode"])
    if any(file_identity(runtime, n.removeprefix("runtime/")) != expected(e["old"]) for n,e in items.items()):
        raise ValueError("Restored payload mismatch")

    # Remove only previously absent, contract-derived empty directories.
    allowed = {str(p) for name in items for p in Path(name.removeprefix("runtime/")).parents if p != Path(".")}
    missing = set(record.get("missing_payload_dirs", []))
    if not missing <= allowed:
        raise ValueError("Unexpected rollback directory scope")
    for rel in sorted(missing, key=lambda n: (len(Path(n).parts), n), reverse=True):
        p = runtime / rel
        if p.exists() or p.is_symlink():
            parents(runtime, rel)
            directory_review(p)
            p.rmdir()
            sync_dir(p.parent)
