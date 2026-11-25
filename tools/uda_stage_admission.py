"""Operator-invoked, isolated real staged-runtime admission check.

Checks source payload and staged interpreter dependencies; runs Flask test
clients with a synthetic config and isolated HOME. No live service actions.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

from tools.uda_runtime_integrity import inventory


SMOKE = r"""
import importlib
import json
from pathlib import Path
import sys

runtime = Path(sys.argv[1]).resolve()
config = Path(sys.argv[2])
sys.path.insert(0, str(runtime))
for name in ("home", "dashboard", "deploy_agent", "approval_centre",
             "onboarding_v2", "uda_manifest_v2_validate"):
    module = importlib.import_module(name)
    if Path(module.__file__).resolve().parent != runtime:
        raise RuntimeError("Unexpected import source: " + name)
import home
import dashboard
headers = {"Authorization": "Basic YWRtaW46Zml4dHVyZS1vbmx5"}
for name, app in (("home", home.create_app(config)),
                  ("dashboard", dashboard.create_app(config))):
    client = app.test_client()
    response = client.get("/health")
    if response.status_code != 200 or response.get_json().get("ok") is not True:
        raise RuntimeError(name + " health failed")
    if client.get("/", headers=headers).status_code != 200:
        raise RuntimeError(name + " index failed")
    if name == "dashboard":
        for route in ("/onboarding", "/approvals"):
            if client.get(route, headers=headers).status_code != 200:
                raise RuntimeError("Review view failed: " + route)
        if client.post("/approvals/request", headers=headers).status_code != 403:
            raise RuntimeError("Unexpected approval permission")
print(json.dumps({"smoke": "PASS", "health": ["home", "dashboard"],
                  "review_views": ["onboarding", "approvals"]}))
"""


def accept(stage: Path) -> dict:
    stage = stage.absolute()
    manifest = inventory(stage)
    runtime = stage / "runtime"
    venv = runtime / "venv"
    for directory in (runtime, venv, venv / "bin"):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Unsafe staged interpreter directory")
    interpreter = venv / "bin/python"
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise ValueError("Staged interpreter missing")
    if not (venv / "pyvenv.cfg").is_file() or (venv / "pyvenv.cfg").is_symlink():
        raise ValueError("Staged virtual environment missing")
    with tempfile.TemporaryDirectory(prefix="uda-stage-admission-") as folder:
        lab = Path(folder)
        config = lab / "config.json"
        config.write_text(json.dumps({"dashboard_token": "fixture-only",
                                     "applications": [],
                                     "identity_db": str(lab / "identity.db")}))
        config.chmod(0o600)
        env = {"HOME": str(lab), "XDG_CONFIG_HOME": str(lab / "config"),
               "XDG_DATA_HOME": str(lab / "data"), "XDG_STATE_HOME": str(lab / "state"),
               "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
               "PIP_CONFIG_FILE": os.devnull}
        def run(*args):
            result = subprocess.run([str(interpreter), "-I", "-B", *args],
                                    cwd=lab, env=env, capture_output=True, text=True,
                                    timeout=60, check=False)
            if result.returncode:
                raise RuntimeError("Staged subprocess failed: " + args[0] +
                                   " (exit " + str(result.returncode) + ")")
            return result.stdout
        prefix = run("-c", "import sys; print(sys.prefix)").strip()
        if Path(prefix).resolve() != venv.resolve():
            raise ValueError("Interpreter is not bound to the staged venv")
        run("-m", "pip", "check")
        result = json.loads(run("-c", SMOKE, str(runtime), str(config)).strip())
        if result["smoke"] != "PASS":
            raise RuntimeError("Incomplete staged smoke")
    if inventory(stage) != manifest:
        raise ValueError("Payload changed during acceptance")
    return {"status": "PASS", "payload_count": manifest["payload_count"],
            "source_bytes_verified": True, "staged_venv_verified": True,
            "pip_check_passed": True, "smoke": result,
            "production_files_modified": False, "systemctl_invoked": False,
            "production_upgrade_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(accept(args.stage), indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc),
                          "production_upgrade_authorized": False}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
