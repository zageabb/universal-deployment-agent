"""Verify candidate bytes before executing its interpreter.

A local receipt binds the candidate to the reviewed source and filesystem
identity. It is not a signature or protection against a malicious same UID.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from tools import uda_permanent_candidate_venv as prep
from tools.uda_runtime_integrity import ROOT, inventory
from tools.uda_stage_admission import SMOKE


def tree(root):
    if prep.identity(root)[3] != 0o700:
        raise ValueError("Candidate must be private")
    entries = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(folder) / name
            rel = str(path.relative_to(root))
            s = path.lstat()
            if s.st_uid != os.getuid():
                raise ValueError("Unexpected candidate owner")
            mode = stat.S_IMODE(s.st_mode)
            if stat.S_ISLNK(s.st_mode):
                target = os.readlink(path)
                # Standard venv interpreter links may point to the base Python.
                if rel in {"bin/python", "bin/python3", "bin/python3.10", "bin/python3.12", "bin/python3.13", "bin/python3.14"}:
                    resolved = path.resolve(strict=True)
                    if not resolved.is_file() or resolved.stat().st_uid != 0 or resolved.stat().st_mode & 0o022:
                        raise ValueError("Unsafe base interpreter")
                    entries[rel] = ["python-link", target, hashlib.sha256(resolved.read_bytes()).hexdigest()]
                elif not Path(target).is_absolute() and path.resolve(strict=True).is_relative_to(root.resolve()):
                    entries[rel] = ["link", target]
                else:
                    raise ValueError("Unexpected candidate symlink")
            elif mode & 0o022 or any(k.startswith("system.posix_acl_") for k in os.listxattr(path, follow_symlinks=False)):
                raise ValueError("Unsafe candidate permissions")
            elif stat.S_ISDIR(s.st_mode):
                entries[rel] = ["directory", mode]
            elif stat.S_ISREG(s.st_mode) and s.st_nlink == 1:
                entries[rel] = ["file", mode, hashlib.sha256(path.read_bytes()).hexdigest()]
            else:
                raise ValueError("Unsafe candidate object")
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def seal(stage, candidate, report):
    return {"candidate": str(candidate), "identity": list(prep.identity(candidate)),
            "tree_sha256": tree(candidate),
            "payload": inventory(stage)["files"],
            "requirements_sha256": hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest(),
            "packages_sha256": report["packages_sha256"]}


def verify(stage, candidate, receipt):
    expected = seal(stage, candidate, receipt)
    if expected != receipt:
        raise ValueError("Candidate identity or bytes changed")
    with tempfile.TemporaryDirectory(prefix="uda-candidate-admission-") as folder:
        lab = Path(folder)
        python = candidate / "bin/python"
        if Path(prep.run(python, ["-c", "import sys; print(sys.prefix)"], lab)).resolve() != candidate.resolve():
            raise ValueError("Candidate prefix mismatch")
        prep.run(python, ["-m", "pip", "check"], lab)
        packages = prep.run(python, ["-m", "pip", "freeze", "--all"], lab)
        if hashlib.sha256(packages.encode()).hexdigest() != receipt["packages_sha256"]:
            raise ValueError("Candidate package inventory changed")
        config = lab / "fixture.json"
        config.write_text(json.dumps({"dashboard_token": "fixture-only", "applications": [],
                                      "identity_db": str(lab / "identity.db")}))
        config.chmod(0o600)
        smoke = json.loads(prep.run(python, ["-c", SMOKE, stage / "runtime", config], lab))
        if smoke.get("smoke") != "PASS":
            raise ValueError("Candidate smoke failed")
    if seal(stage, candidate, receipt) != receipt:
        raise ValueError("Candidate changed during verification")
    return receipt
