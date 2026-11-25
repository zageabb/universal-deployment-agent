"""CI-only actual payload + real systemd + HTTP acceptance; never production."""
from pathlib import Path
import base64
import json
import os
import subprocess
import tempfile
from urllib.request import Request, urlopen

from lifecycle_acceptance import guard, wait_for
from tools import uda_controlled_activation as model
from tools import uda_combined_release_transaction as combined
from tools import uda_parallel_venv as venv
from tools import uda_integrated_install_rehearsal as transaction
from tools.uda_runtime_integrity import ROOT, inventory, payload_paths

UNIT_DIR = Path("/etc/systemd/system")
PREFIX = "uda-ci-combined-"
NAMES = {u: PREFIX + u for u in model.UNITS}
PORTS = {"home": 18771, "dashboard": 18772}
EVIDENCE = Path("/tmp/uda-combined-real-activation.json")
PYTHON = "/opt/uda-v2-test-venv/bin/python"


def ctl(action, unit=None):
    if action == "daemon-reload" and unit is None:
        args = []
    elif action in {"start", "stop", "enable", "disable", "show"} and unit in NAMES:
        args = [NAMES[unit]]
    else:
        raise ValueError("Unknown disposable operation")
    return subprocess.run(["systemctl", action, *args], check=True, capture_output=True,
                          text=True, timeout=25).stdout


def states():
    result = {}
    for u in model.UNITS:
        props = dict(line.split("=", 1) for line in ctl("show", u).splitlines() if "=" in line)
        result[u] = model.State(props["ActiveState"], props["UnitFileState"],
                                props["LoadState"], props["SubState"], props.get("Result", "success"))
    model.validate(result)
    return result


def health(name, failed=False):
    # Real Flask endpoint; the negative scenario deliberately probes a missing
    # endpoint on the actual candidate dashboard (HTTP 404).
    path = "/missing-fixture-health" if failed and name == "dashboard" else "/health"
    def check():
        request = Request(f"http://127.0.0.1:{PORTS[name]}{path}")
        if name == "dashboard":
            request.add_header("Authorization", "Basic " + base64.b64encode(b"admin:fixture-only").decode())
        with urlopen(request, timeout=2) as r:
            return r.status == 200 and json.loads(r.read())["ok"] is True
    if failed and name == "dashboard":
        if not health(name):
            raise RuntimeError("Candidate dashboard never became ready")
        from urllib.error import HTTPError
        try:
            check()
        except HTTPError as exc:
            if exc.code == 404:
                return False
            raise
    return wait_for(check)


def activate(original, failed=False):
    for action, target in model.plan(original):
        if action == "start":
            ctl("start", target)
        elif not health(target, failed):
            return False
    return states() == original


def isolate():
    for u in model.TIMERS + tuple(reversed(model.WEB)):
        ctl("stop", u)
    if any(s.active != "inactive" for s in states().values()):
        raise RuntimeError("Fixture isolation failed")


def scenario(failed):
    with tempfile.TemporaryDirectory(prefix="uda-journal-lab-") as folder:
        root = Path(folder)
        for d in ("runtime", "backup", "candidate"):
            (root / d).mkdir(mode=0o700)
        stage = root / "candidate"
        dep = root / "uda-venv-lab-dependencies"
        dep.mkdir(mode=0o700)
        live, _, new = venv.layout(dep)
        for environment, marker in ((live, "old"), (new, "new")):
            subprocess.run(["/usr/bin/python3", "-m", "venv", str(environment)], check=True, timeout=90)
            subprocess.run([str(environment / "bin/python"), "-m", "pip", "install", "--no-index", "--find-links=/opt/uda-wheels", "-r", str(ROOT / "requirements.txt")], check=True, timeout=90)
            transaction.put(environment / ".uda-fixture", marker.encode(), 0o600)
        def interpreter_prefix():
            return Path(subprocess.check_output([str(live / "bin/python"), "-I", "-B", "-c", "import sys; print(sys.prefix)"], text=True, timeout=10).strip()).resolve()
        if interpreter_prefix() != live:
            raise RuntimeError("Old interpreter mismatch")
        for n, source in payload_paths(ROOT).items():
            for d in ("runtime", "backup", "candidate"):
                (root / d / n).parent.mkdir(parents=True, exist_ok=True)
            data = source.read_bytes()
            transaction.put(stage / n, data, 0o644)
            # Previous runnable code from the same revision, with distinct bytes.
            prior = data + (b"\n<!-- disposable previous release -->\n" if n.endswith(".html") else b"\n# disposable previous release\n") if n in combined.REPLACE else data
            transaction.put(root / "runtime" / n, prior, 0o644)
        payload = inventory(stage)["files"]
        manifest = {n: payload[n] for n in combined.REPLACE}
        before = {n: transaction.identity(root / "runtime" / n) for n in manifest}
        config = root / "config.json"
        transaction.put(config, json.dumps({"dashboard_token": "fixture-only",
                         "applications": []}).encode(), 0o600)
        files = {}
        for u in model.UNITS:
            if u in model.TIMERS:
                content = "[Timer]\nOnActiveSec=1d\nUnit=" + NAMES[u.replace(".timer", ".service")] + "\n[Install]\nWantedBy=timers.target\n"
            elif u in model.WORKERS:
                content = "[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
            else:
                name = "home" if u == model.WEB[0] else "dashboard"
                runtime = root / "runtime/runtime"
                content = (f"[Service]\nWorkingDirectory={runtime}\n"
                           f"ExecStart={live / 'bin/python'} {runtime / (name + '.py')} --config {config} "
                           f"--host 127.0.0.1 --port {PORTS[name]}\n"
                           "[Install]\nWantedBy=multi-user.target\n")
            files[u] = content
        owned = []
        try:
            for u, content in files.items():
                with (UNIT_DIR / NAMES[u]).open("x") as f:
                    owned.append(u)
                    f.write(content)
            ctl("daemon-reload")
            for u in model.WEB + model.TIMERS[:2]:
                ctl("enable", u)
            for u in model.WEB + (model.TIMERS[0], model.TIMERS[2]):
                ctl("start", u)
            if not all(health(n) for n in PORTS):
                raise RuntimeError("Prior runtime unhealthy")
            original = states()
            isolate()
            model.admission(original, states(), writers_quiescent=True, backup_verified=True)
            combined.apply(root, manifest, "")
            if combined.phase(root) != "awaiting_health" or interpreter_prefix() != new:
                raise RuntimeError("Combined candidate interpreter mismatch")
            if transaction.journal.load(root)["phase"] != "complete":
                raise RuntimeError("Payload not committed")
            result = activate(original, failed)
            if failed:
                if result or any(states()[u].active != "inactive" for u in model.TIMERS):
                    raise RuntimeError("Negative health gate did not block timers")
                isolate()
                combined.recover(root, manifest, "")
                if combined.phase(root) != "rolled_back" or interpreter_prefix() != live:
                    raise RuntimeError("Combined interpreter rollback mismatch")
                if any(transaction.identity(root / "runtime" / n) != v for n, v in before.items()):
                    raise RuntimeError("Prior payload mismatch")
                if not activate(original):
                    raise RuntimeError("Restored activation failed")
            elif not result:
                raise RuntimeError("Candidate activation failed")
            else:
                combined.record(root, "fixture_accepted")
            if states() != original or json.loads(config.read_text())["dashboard_token"] != "fixture-only":
                raise RuntimeError("Baseline mismatch")
            return {"actual_flask_health": True, "timer_states_preserved": True,
                    "real_interpreter_switched": True, "original_interpreter_restored": failed,
                    "combined_phase": combined.phase(root),
                    "failed_probe_detected": failed, "payload_restored": failed,
                    "payload_count": len(manifest)}
        finally:
            for u in owned:
                ctl("stop", u)
                if u in model.WEB + model.TIMERS:
                    ctl("disable", u)
            for u in owned:
                (UNIT_DIR / NAMES[u]).unlink()
            ctl("daemon-reload")


def main():
    guard()
    if any((UNIT_DIR / n).exists() or (UNIT_DIR / n).is_symlink() for n in NAMES.values()):
        raise RuntimeError("Fixture units already exist")
    result = {"success": scenario(False), "failed_health": scenario(True),
              "production_upgrade_authorized": False, "synthetic_units_only": True}
    EVIDENCE.write_text(json.dumps(result, indent=2))
    print("PASS: combined journal, real interpreter and Flask health under disposable systemd")


if __name__ == "__main__":
    main()
