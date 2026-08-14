#!/usr/bin/env python3
"""Small, fail-closed deployment poller for multiple Git repositories."""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from urllib.request import urlopen


class DeployError(RuntimeError):
    pass


def run(command: list[str], cwd: Path | None = None, timeout: int = 120) -> str:
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeployError(f"Could not run {command[0]}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise DeployError(f"{' '.join(command)} failed ({result.returncode}): {detail}")
    return result.stdout.strip()


def load_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise DeployError(f"Configuration is unreadable: {exc}") from exc
    if not isinstance(value.get("applications"), list):
        raise DeployError("Configuration must contain an applications list")
    names = set()
    for app in value["applications"]:
        required = {"name", "repo_path", "branch", "restart_command", "health_url"}
        missing = required - set(app)
        if missing:
            raise DeployError(f"Application is missing fields: {sorted(missing)}")
        if app["name"] in names:
            raise DeployError(f"Duplicate application name: {app['name']}")
        names.add(app["name"])
        if not isinstance(app["restart_command"], list) or not app["restart_command"]:
            raise DeployError(f"{app['name']} restart_command must be a non-empty argument list")
    return value


def git(repo: Path, *arguments: str, timeout: int = 120) -> str:
    return run(["git", *arguments], cwd=repo, timeout=timeout)


def health_check(url: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=3) as response:
                if 200 <= response.status < 300:
                    return
                last_error = f"HTTP {response.status}"
        except Exception as exc:  # network errors are reported and retried
            last_error = str(exc)
        time.sleep(1)
    raise DeployError(f"Health check failed for {url}: {last_error}")


def inspect_application(app: dict[str, Any], fetch: bool = True) -> dict[str, Any]:
    repo = Path(app["repo_path"]).expanduser().resolve()
    if not (repo / ".git").exists():
        raise DeployError(f"Repository does not exist: {repo}")
    branch = str(app["branch"])
    current_branch = git(repo, "branch", "--show-current")
    if current_branch != branch:
        raise DeployError(f"Expected branch {branch}, found {current_branch or 'detached HEAD'}")
    dirty = git(repo, "status", "--porcelain")
    if fetch:
        git(repo, "fetch", "--quiet", "origin", branch, timeout=int(app.get("git_timeout", 120)))
    local = git(repo, "rev-parse", "HEAD")
    remote = git(repo, "rev-parse", f"origin/{branch}")
    return {"repo": repo, "dirty": dirty, "local": local, "remote": remote, "update_available": local != remote}


def deploy_application(app: dict[str, Any], dry_run: bool, logger: logging.Logger) -> dict[str, Any]:
    name = app["name"]
    if not app.get("enabled", False):
        return {"name": name, "status": "disabled"}
    state = inspect_application(app)
    if state["dirty"]:
        if app.get("auto_deploy", False):
            raise DeployError("Working tree has local changes; refusing automatic deployment")
        return {"name": name, "status": "monitored_dirty", "commit": state["local"],
                "update_available": state["update_available"]}
    if not state["update_available"]:
        return {"name": name, "status": "current", "commit": state["local"]}
    if dry_run or not app.get("auto_deploy", False):
        return {"name": name, "status": "update_available", "from": state["local"], "to": state["remote"]}
    repo, previous = state["repo"], state["local"]
    logger.info("%s updating %s -> %s", name, previous[:12], state["remote"][:12])
    git(repo, "merge", "--ff-only", f"origin/{app['branch']}")
    try:
        for command in app.get("update_commands", []):
            run([str(part) for part in command], cwd=repo, timeout=int(app.get("command_timeout", 300)))
        run([str(part) for part in app["restart_command"]], timeout=int(app.get("restart_timeout", 60)))
        health_check(str(app["health_url"]), int(app.get("health_timeout", 30)))
    except DeployError:
        if app.get("rollback", True):
            logger.exception("%s deployment failed; rolling back to %s", name, previous[:12])
            git(repo, "reset", "--hard", previous)
            run([str(part) for part in app["restart_command"]], timeout=int(app.get("restart_timeout", 60)))
            health_check(str(app["health_url"]), int(app.get("health_timeout", 30)))
        raise
    return {"name": name, "status": "deployed", "from": previous, "to": state["remote"]}


def configure_logging(config: dict[str, Any], verbose: bool) -> logging.Logger:
    logger = logging.getLogger("deployment-agent")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    log_path = config.get("log_file")
    if log_path:
        path = Path(log_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=5)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def execute(config: dict[str, Any], dry_run: bool, verbose: bool) -> list[dict[str, Any]]:
    logger = configure_logging(config, verbose)
    lock_path = Path(config.get("lock_file", "/tmp/deployment-agent.lock")).expanduser()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    results = []
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DeployError("Another deployment-agent run is active") from exc
        for app in config["applications"]:
            try:
                result = deploy_application(app, dry_run, logger)
                logger.info("%s: %s", app["name"], result["status"])
            except DeployError as exc:
                result = {"name": app.get("name", "unknown"), "status": "blocked", "error": str(exc)}
                logger.error("%s: %s", result["name"], exc)
            results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely update and restart registered Git applications")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report without changing applications")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    try:
        results = execute(load_config(args.config), args.dry_run, args.verbose)
    except DeployError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps({"ok": not any(item["status"] == "blocked" for item in results), "applications": results}, indent=2))
    return 1 if any(item["status"] == "blocked" for item in results) else 0


if __name__ == "__main__":
    sys.exit(main())
