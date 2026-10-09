#!/usr/bin/env python3
"""Safely publish deployed applications that declare and prove UDA subpath support."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from deploy_agent import DeployError, load_config

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def run(command: list[str], cwd: Path | None = None, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout)


def git(repo: Path, *arguments: str) -> str:
    result = run(["git", "-C", str(repo), *arguments], timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def python_for(app: dict, repo: Path) -> Path | None:
    candidates: list[Path] = []
    if app.get("python"):
        candidates.append(Path(app["python"]).expanduser())
    candidates.extend((repo / ".venv/bin/python", repo / "venv/bin/python"))
    for command in app.get("update_commands", []):
        if command and isinstance(command[0], str):
            executable = Path(command[0]).expanduser()
            if executable.name.startswith("pip"):
                candidates.append(executable.with_name("python"))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    fallback = shutil.which("python3")
    return Path(fallback) if fallback else None


def origin_for(app: dict) -> str:
    raw = app.get("app_url") or app.get("health_url") or ""
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise RuntimeError("missing valid app_url/health_url")
    authority = parts.hostname if parts.port is None else f"{parts.hostname}:{parts.port}"
    return f"{parts.scheme}://{authority}"


def candidate_reason(app: dict) -> tuple[bool, str]:
    if not app.get("enabled") or app.get("kind", "service") != "service":
        return False, "not an enabled service"
    if app.get("proxy_enabled"):
        return False, "already proxied"
    if app.get("show_on_home") is False:
        return False, "not published on Application Home"
    repo = Path(app["repo_path"]).expanduser().resolve()
    marker = repo / "tests/test_uda_subpath.py"
    if not marker.is_file():
        return False, "no tests/test_uda_subpath.py migration marker"
    if not (repo / ".git").is_dir():
        return False, "repository checkout missing"
    if git(repo, "status", "--porcelain"):
        return False, "working tree is dirty"
    branch = app.get("branch", "main")
    if git(repo, "branch", "--show-current") != branch:
        return False, f"checkout is not on {branch}"
    if git(repo, "rev-parse", "HEAD") != git(repo, "rev-parse", f"origin/{branch}"):
        return False, "deployed commit does not match origin branch"
    if not app.get("group"):
        return False, "application has no UDA group"
    slug = app.get("proxy_slug") or app["name"]
    if not SLUG.fullmatch(slug):
        return False, "proxy slug is unsafe"
    if python_for(app, repo) is None:
        return False, "Python test interpreter unavailable"
    return True, "ready for validation"


def validate_candidate(app: dict) -> dict:
    repo = Path(app["repo_path"]).expanduser().resolve()
    interpreter = python_for(app, repo)
    assert interpreter is not None
    timeout = int(app.get("proxy_test_timeout", 900))
    command = app.get("proxy_test_command") or [str(interpreter), "-m", "pytest", "-q"]
    result = run(command, cwd=repo, timeout=timeout)
    if result.returncode:
        tail = (result.stdout + "\n" + result.stderr).strip()[-2000:]
        raise RuntimeError(f"test suite failed: {tail}")

    slug = app.get("proxy_slug") or app["name"]
    prefix = f"/apps/{slug}"
    request = Request(origin_for(app) + "/", headers={
        "Host": urlsplit(load_config(CONFIG_PATH)["public_base_url"]).hostname or "localhost",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Prefix": prefix,
    })
    # Do not follow a login redirect to the (not-yet-published) public URL.
    # A redirect is valid evidence only when its Location stays in this mount.
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        response = build_opener(NoRedirect).open(request, timeout=15)
    except HTTPError as exc:
        response = exc
    with response:
        status = response.code
        body = response.read(1_000_000).decode("utf-8", "replace")
        location = response.headers.get("Location", "")
    if status in {301, 302, 303, 307, 308}:
        target = urlsplit(location)
        public_host = urlsplit(load_config(CONFIG_PATH)["public_base_url"]).hostname
        if target.scheme and target.scheme not in {"https", "http"}:
            raise RuntimeError("prefixed backend redirects to an unsafe scheme")
        if target.netloc and target.hostname != public_host:
            raise RuntimeError("prefixed backend redirects outside public UDA host")
        if not (target.path == prefix or target.path.startswith(prefix + "/")):
            raise RuntimeError("prefixed backend redirects outside its application mount")
    elif status == 200:
        if prefix not in body:
            raise RuntimeError("live backend response does not contain the forwarded prefix")
    else:
        raise RuntimeError(f"prefixed backend probe returned HTTP {status}")
    return {"tests": command, "origin": origin_for(app), "prefix": prefix}


def write_config(path: Path, config: dict) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=path.name + ".", delete=False) as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def reload_proxy() -> None:
    result = run(["systemctl", "--user", "start", "uda-proxy-refresh.service"], timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "proxy refresh failed")


def verify_ingress(config: dict, app: dict) -> None:
    slug = app.get("proxy_slug") or app["name"]
    url = config["public_base_url"].rstrip("/") + f"/apps/{slug}/"
    try:
        with urlopen(Request(url), timeout=20) as response:
            status = response.status
    except HTTPError as exc:
        status = exc.code
    except URLError as exc:
        raise RuntimeError(f"public ingress unavailable: {exc}") from exc
    if status not in {401, 403}:
        raise RuntimeError(f"unauthenticated public ingress returned HTTP {status}, expected 401/403")


def publish(config_path: Path, config: dict, app_name: str, dry_run: bool) -> dict:
    app = next(item for item in config["applications"] if item["name"] == app_name)
    evidence = validate_candidate(app)
    if dry_run:
        return {"name": app_name, "status": "validated", **evidence}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = config_path.with_name(f"{config_path.name}.before-auto-proxy-{app_name}-{stamp}")
    shutil.copy2(config_path, backup)
    try:
        app["app_url"] = origin_for(app) + "/"
        app["proxy_enabled"] = True
        app["proxy_slug"] = app.get("proxy_slug") or app["name"]
        app["allowed_groups"] = [app["group"]]
        write_config(config_path, config)
        reload_proxy()
        verify_ingress(config, app)
    except Exception:
        shutil.copy2(backup, config_path)
        reload_proxy()
        raise
    return {"name": app_name, "status": "published", "backup": str(backup), **evidence}


def save_state(path: Path, results: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_config(path, {"checked_at": datetime.now(timezone.utc).isoformat(), "results": results})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    global CONFIG_PATH
    CONFIG_PATH = arguments.config.expanduser().resolve()
    state_path = arguments.state.expanduser().resolve()
    lock_path = state_path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        config = load_config(CONFIG_PATH)
        for app in config["applications"]:
            try:
                ready, reason = candidate_reason(app)
                if not ready:
                    if reason not in {"already proxied", "not an enabled service", "not published on Application Home"}:
                        results.append({"name": app.get("name"), "status": "skipped", "reason": reason})
                    continue
                results.append(publish(CONFIG_PATH, config, app["name"], arguments.dry_run))
                config = load_config(CONFIG_PATH)
            except Exception as exc:
                results.append({"name": app.get("name"), "status": "blocked", "reason": str(exc)})
        save_state(state_path, results)
    print(json.dumps({"ok": not any(item["status"] == "blocked" for item in results), "results": results}, indent=2))
    return 1 if any(item["status"] == "blocked" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
