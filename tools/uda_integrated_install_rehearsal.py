"""Full installer payload rehearsal in a self-created disposable directory.

No production destination parameter, service calls, or dependency changes.
Uses the journal prototype's durable write primitives. Linux/POSIX only.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
from pathlib import Path
import signal
import stat
import tempfile
import uuid

from tools import uda_install_journal as journal
from tools.uda_runtime_integrity import ROOT, inventory, payload_paths, regular_file


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def identity(path: Path):
    if path.is_symlink():
        raise ValueError("Unexpected symlink")
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("Unexpected non-file")
    return {"sha256": journal.checksum(path.read_bytes()), "mode": mode(path)}


def put(path: Path, data: bytes, permissions: int) -> None:
    # Parents are precreated in the private lab.
    journal.durable_write(path, data, permissions)


def interrupt(boundary, requested):
    if boundary == requested:
        os.kill(os.getpid(), signal.SIGKILL)


def apply(root, manifest, crash):
    with journal.locked(root):
        if (root / "journal.json").exists():
            raise ValueError("Existing transaction")
        entries = {}
        for name, item in manifest.items():
            old = identity(root / "runtime" / name)
            candidate = regular_file(root / "candidate", name)
            expected = {"sha256": item["sha256"], "mode": item["mode"]}
            if identity(candidate) != expected:
                raise ValueError("Candidate mismatch")
            if old is not None:
                backup = root / "backup" / name
                put(backup, (root / "runtime" / name).read_bytes(), old["mode"])
                if identity(backup) != old:
                    raise ValueError("Backup mismatch")
            entries[name] = {"old": old, "new": expected, "state": "pending"}
        record = {"version": 2, "id": str(uuid.uuid4()), "phase": "prepared", "entries": entries}
        journal.save(root, record)
        for name, entry in entries.items():
            record["phase"] = "applying"
            entry["state"] = "intent"
            journal.save(root, record)
            interrupt("before:" + name, crash)
            data = regular_file(root / "candidate", name).read_bytes()
            if journal.checksum(data) != entry["new"]["sha256"]:
                raise ValueError("Candidate changed")
            dest = root / "runtime" / name
            put(dest, data, entry["new"]["mode"])
            interrupt("after:" + name, crash)
            if identity(dest) != entry["new"]:
                raise ValueError("Replacement mismatch")
            entry["state"] = "applied"
            journal.save(root, record)
        if any(identity(root / "runtime" / n) != e["new"] for n, e in entries.items()):
            raise ValueError("Final payload mismatch")
        record["phase"] = "complete"
        journal.save(root, record)


def recover(root, manifest, crash):
    with journal.locked(root):
        record = journal.load(root)
        entries = record["entries"]
        if (record["version"] != 2 or record["phase"] not in
                {"prepared", "applying", "recovering"} or set(entries) != set(manifest)):
            raise ValueError("Unexpected transaction")
        for name, entry in entries.items():
            expected = {"sha256": manifest[name]["sha256"], "mode": manifest[name]["mode"]}
            if entry["new"] != expected or entry["state"] not in {"pending", "intent", "applied", "restored"}:
                raise ValueError("Invalid journal entry")
            if entry["old"] is not None and identity(root / "backup" / name) != entry["old"]:
                raise ValueError("Backup mismatch")
            allowed = [entry["old"]]
            if entry["state"] in {"intent", "applied"}:
                allowed.append(entry["new"])
            if identity(root / "runtime" / name) not in allowed:
                raise ValueError("Unexpected installed identity")
        record["phase"] = "recovering"
        journal.save(root, record)
        for name, entry in reversed(list(entries.items())):
            dest = root / "runtime" / name
            if entry["old"] is None:
                dest.unlink(missing_ok=True)
                journal.sync_dir(dest.parent)
            else:
                put(dest, (root / "backup" / name).read_bytes(), entry["old"]["mode"])
            interrupt("restore:" + name, crash)
            entry["state"] = "restored"
            journal.save(root, record)
        if any(identity(root / "runtime" / n) != e["old"] for n, e in entries.items()):
            raise ValueError("Rollback mismatch")
        record["phase"] = "rolled_back"
        journal.save(root, record)


def run_child(fn, root, manifest, crash):
    child = multiprocessing.get_context("fork").Process(target=fn, args=(root, manifest, crash))
    child.start()
    child.join(90)
    if child.is_alive():
        child.kill()
        child.join()
        raise RuntimeError("Rehearsal child timed out")
    expected = -signal.SIGKILL if crash else 0
    if child.exitcode != expected:
        raise RuntimeError("Unexpected child exit: " + str(child.exitcode))


def rehearse(stage: Path, scenario: str = "interrupted") -> dict:
    if scenario not in {"success", "interrupted", "recovery-interrupted"}:
        raise ValueError("Unknown scenario")
    manifest = inventory(stage)["files"]
    names = sorted(manifest)
    with tempfile.TemporaryDirectory(prefix="uda-journal-lab-") as folder:
        root = Path(folder)
        for directory in ("runtime", "backup", "candidate"):
            (root / directory).mkdir(mode=0o700)
        for name in names:
            for directory in ("runtime", "backup", "candidate"):
                (root / directory / name).parent.mkdir(parents=True, exist_ok=True)
            data = regular_file(stage, name).read_bytes()
            if journal.checksum(data) != manifest[name]["sha256"]:
                raise ValueError("Stage changed during copy")
            put(root / "candidate" / name, data, manifest[name]["mode"])
            if name != names[0]:
                put(root / "runtime" / name, ("previous:" + name).encode(), 0o640)
        sentinel = root / "runtime/unmanaged-state"
        put(sentinel, b"preserve", 0o600)
        before = {name: identity(root / "runtime" / name) for name in names}
        crash = "" if scenario == "success" else "after:" + names[len(names)//2]
        run_child(apply, root, manifest, crash)
        if crash:
            if journal.load(root)["phase"] != "applying":
                raise ValueError("Interrupted phase not detected")
            if scenario == "recovery-interrupted":
                run_child(recover, root, manifest, "restore:" + names[len(names)//2])
                if journal.load(root)["phase"] != "recovering":
                    raise ValueError("Interrupted recovery not detected")
            run_child(recover, root, manifest, "")
            if journal.load(root)["phase"] != "rolled_back":
                raise ValueError("Rollback not recorded")
            expected = before
        else:
            if journal.load(root)["phase"] != "complete":
                raise ValueError("Completion not recorded")
            expected = {n: {"sha256": e["sha256"], "mode": e["mode"]} for n, e in manifest.items()}
        if any(identity(root / "runtime" / n) != e for n, e in expected.items()):
            raise ValueError("Final runtime mismatch")
        if sentinel.read_bytes() != b"preserve" or mode(sentinel) != 0o600:
            raise ValueError("Unmanaged state changed")
        return {"status": "PASS", "scenario": scenario, "payload_count": len(names),
                "phase": journal.load(root)["phase"], "all_payload_identities_verified": True,
                "unmanaged_state_preserved": True, "production_files_modified": False,
                "systemctl_invoked": False, "production_upgrade_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--scenario", choices=["success", "interrupted", "recovery-interrupted"],
                        default="interrupted")
    args = parser.parse_args()
    print(json.dumps(rehearse(args.stage, args.scenario), indent=2))


if __name__ == "__main__":
    main()
