"""Prepare a candidate venv at its final path; never switch the live interpreter.

Default operation rehearses in a private temporary directory. Actual candidate
creation requires an explicit flag and a fresh production baseline.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from tools import uda_production_admission as admission
from tools.uda_stage_admission import SMOKE
from tools.uda_runtime_integrity import ROOT, inventory


def identity(path):
    s = path.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid():
        raise ValueError("Unsafe environment directory")
    return (s.st_dev, s.st_ino, s.st_uid, stat.S_IMODE(s.st_mode))


def vacant(path):
    if path.exists() or path.is_symlink():
        raise ValueError("Candidate destination already exists")


def run(exe, args, lab):
    env = {"HOME": str(lab), "XDG_CONFIG_HOME": str(lab / "config"),
           "XDG_DATA_HOME": str(lab / "data"), "XDG_STATE_HOME": str(lab / "state"),
           "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
           "PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    result = subprocess.run([str(exe), "-I", "-B", *map(str, args)],
                            cwd=lab, env=env, capture_output=True, text=True,
                            timeout=240, check=False)
    if result.returncode:
        raise RuntimeError("Candidate subprocess failed: " + str(args[0]) +
                           " (exit " + str(result.returncode) + ")")
    return result.stdout.strip()


def prepare(stage, destination, lab):
    before = inventory(stage)
    vacant(destination)
    base = Path(run(stage / "runtime/venv/bin/python",
                    ["-c", "import sys; print(sys._base_executable)"], lab))
    if not base.is_absolute() or not base.is_file():
        raise ValueError("Base interpreter unavailable")
    # Reserve the exact path exclusively; never overwrite or reuse a candidate.
    destination.mkdir(mode=0o700)
    reserved = identity(destination)
    run(base, ["-m", "venv", destination], lab)
    python = destination / "bin/python"
    if Path(run(python, ["-c", "import sys; print(sys.prefix)"], lab)).resolve() != destination.resolve():
        raise ValueError("Candidate prefix mismatch")
    run(python, ["-m", "pip", "install", "--no-input", "-r", ROOT / "requirements.txt"], lab)
    run(python, ["-m", "pip", "check"], lab)
    config = lab / "fixture.json"
    config.write_text(json.dumps({"dashboard_token": "fixture-only", "applications": [],
                                  "identity_db": str(lab / "identity.db")}))
    config.chmod(0o600)
    smoke = json.loads(run(python, ["-c", SMOKE, stage / "runtime", config], lab))
    if smoke.get("smoke") != "PASS" or inventory(stage) != before or identity(destination) != reserved:
        raise ValueError("Candidate acceptance mismatch")
    packages = run(python, ["-m", "pip", "freeze", "--all"], lab)
    return {"python": run(python, ["--version"], lab), "candidate": str(destination),
            "candidate_identity": list(reserved), "pip_check_passed": True,
            "smoke": smoke, "packages": packages.splitlines(),
            "packages_sha256": hashlib.sha256(packages.encode()).hexdigest(),
            "requirements_sha256": hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()}


def execute(stage, create_candidate=False):
    stage = stage.absolute()
    with tempfile.TemporaryDirectory(prefix="uda-candidate-preparation-") as folder:
        lab = Path(folder)
        if not create_candidate:
            report = prepare(stage, lab / "venv-v2", lab)
            return {**report, "status": "REHEARSAL_PASS", "candidate_retained": False,
                    "production_files_modified": False, "live_venv_switched": False,
                    "production_upgrade_authorized": False}
        if os.getuid() == 0:
            raise ValueError("Do not run as root")
        admission.inspect(stage)
        runtime = Path.home() / ".local/share/deployment-agent"
        admission.directory_review(runtime)
        live = runtime / "venv"
        old = identity(live)
        retained = runtime / "venv-v1-retained"
        vacant(retained)
        candidate = runtime / "venv-v2"
        vacant(candidate)
        report = prepare(stage, candidate, lab)
        if identity(live) != old:
            raise ValueError("Live environment identity changed")
        vacant(retained)
        return {**report, "status": "CANDIDATE_READY", "candidate_retained": True,
                "production_files_modified": True, "live_venv_switched": False,
                "live_venv_directory_identity_unchanged": True,
                "production_upgrade_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--create-candidate", action="store_true",
                        help="Create only the new permanent candidate directory; no activation")
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args.stage, args.create_candidate), indent=2))
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "REVIEW", "error": str(exc),
                          "partial_candidate_may_exist": args.create_candidate,
                          "production_upgrade_authorized": False}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
