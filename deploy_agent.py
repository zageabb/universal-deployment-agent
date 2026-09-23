#!/usr/bin/env python3
"""Small, fail-closed deployment poller for multiple Git repositories."""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import re
import socket
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.request import urlopen
from urllib.parse import urlsplit

from ui_groups import DEFAULT_GROUP, clean_group_name

VERSION = "1.6.0"

SERVICE_UNIT_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")
SAFE_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
MANAGED_UNIT_MARKER = "# Managed by Universal Deployment Agent; do not edit."
WEEKDAYS = {
    "monday": "Mon", "tuesday": "Tue", "wednesday": "Wed",
    "thursday": "Thu", "friday": "Fri", "saturday": "Sat", "sunday": "Sun",
}


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


def argument_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(part, str) and part for part in value):
        raise DeployError(f"{label} must be a non-empty argument list")
    if any("\x00" in part or "\n" in part or "\r" in part for part in value):
        raise DeployError(f"{label} contains an invalid control character")
    return value


def safe_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SAFE_NAME_PATTERN.fullmatch(value):
        raise DeployError(f"{label} must contain only lowercase letters, numbers, and internal hyphens")
    return value


def scheduled_time(value: Any, label: str) -> tuple[int, int]:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", str(value))
    if not match:
        raise DeployError(f"{label} must use 24-hour HH:MM format")
    return int(match.group(1)), int(match.group(2))


def schedule_to_on_calendar(job: dict[str, Any]) -> str:
    schedule = job.get("schedule")
    if schedule == "daily":
        hour, minute = scheduled_time(job.get("time"), f"{job['name']} time")
        return f"*-*-* {hour:02d}:{minute:02d}:00"
    if schedule == "hourly":
        minute = job.get("minute", 0)
        if not isinstance(minute, int) or isinstance(minute, bool) or not 0 <= minute <= 59:
            raise DeployError(f"{job['name']} minute must be an integer from 0 to 59")
        return f"*-*-* *:{minute:02d}:00"
    if schedule == "weekly":
        weekday = str(job.get("weekday", "")).lower()
        if weekday not in WEEKDAYS:
            raise DeployError(f"{job['name']} weekday must be a full English weekday name")
        hour, minute = scheduled_time(job.get("time"), f"{job['name']} time")
        return f"{WEEKDAYS[weekday]} *-*-* {hour:02d}:{minute:02d}:00"
    if schedule == "on-calendar":
        expression = job.get("on_calendar")
        if not isinstance(expression, str) or not expression.strip():
            raise DeployError(f"{job['name']} on_calendar must be a non-empty systemd expression")
        if any(character in expression for character in "\x00\n\r"):
            raise DeployError(f"{job['name']} on_calendar contains an invalid control character")
        return expression.strip()
    raise DeployError(f"{job['name']} schedule must be daily, hourly, weekly, or on-calendar")


def validate_scheduled_jobs(app: dict[str, Any]) -> None:
    jobs = app.get("scheduled_jobs", [])
    if not isinstance(jobs, list):
        raise DeployError(f"{app['name']} scheduled_jobs must be a list")
    if jobs:
        safe_name(app.get("name"), "Application name with scheduled jobs")
    names: set[str] = set()
    for job in jobs:
        if not isinstance(job, dict):
            raise DeployError(f"{app['name']} scheduled job must be an object")
        name = safe_name(job.get("name"), f"{app['name']} scheduled job name")
        if name in names:
            raise DeployError(f"Duplicate scheduled job name for {app['name']}: {name}")
        names.add(name)
        argument_list(job.get("command"), f"{app['name']}/{name} command")
        schedule_to_on_calendar(job)
        if "description" in job and not isinstance(job["description"], str):
            raise DeployError(f"{app['name']}/{name} description must be a string")
        if "environment_file" in job and not isinstance(job["environment_file"], str):
            raise DeployError(f"{app['name']}/{name} environment_file must be a path string")
        for field in ("enabled", "persistent"):
            if field in job and not isinstance(job[field], bool):
                raise DeployError(f"{app['name']}/{name} {field} must be true or false")


def load_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise DeployError(f"Configuration is unreadable: {exc}") from exc
    if not isinstance(value.get("applications"), list):
        raise DeployError("Configuration must contain an applications list")
    groups = value.get("groups", [])
    if not isinstance(groups, list):
        raise DeployError("groups must be a list")
    seen_groups: set[str] = set()
    for raw_group in groups:
        try:
            group = clean_group_name(raw_group)
        except ValueError as exc:
            raise DeployError(str(exc)) from exc
        if group == DEFAULT_GROUP:
            raise DeployError(f"{DEFAULT_GROUP} is reserved for ungrouped applications")
        key = group.casefold()
        if key in seen_groups:
            raise DeployError(f"Duplicate group name: {group}")
        seen_groups.add(key)
    names = set()
    for app in value["applications"]:
        required = {"name", "repo_path", "branch"}
        if app.get("kind", "service") not in {"service", "library"}:
            raise DeployError("kind must be service or library")
        if app.get("kind", "service") == "service":
            required |= {"restart_command", "health_url"}
        elif not app.get("update_commands"):
            raise DeployError("Library requires update_commands to validate the revision")
        missing = required - set(app)
        if missing:
            raise DeployError(f"Application is missing fields: {sorted(missing)}")
        if app["name"] in names:
            raise DeployError(f"Duplicate application name: {app['name']}")
        names.add(app["name"])
        if "group" in app:
            try:
                clean_group_name(app["group"])
            except ValueError as exc:
                raise DeployError(f"{app['name']} {exc}") from exc
        if app.get("kind", "service") == "service" and (not isinstance(app["restart_command"], list) or not app["restart_command"]):
            raise DeployError(f"{app['name']} restart_command must be a non-empty argument list")
        service_unit = app.get("service_unit")
        if service_unit is not None and not SERVICE_UNIT_PATTERN.fullmatch(str(service_unit)):
            raise DeployError(f"{app['name']} service_unit must be a valid .service unit name")
        validate_scheduled_jobs(app)
    return value


def unit_names(app_name: str, job_name: str) -> tuple[str, str]:
    base = f"uda-{app_name}-{job_name}"
    return f"{base}.service", f"{base}.timer"


def systemd_quote(value: str) -> str:
    if any(character in value for character in "\x00\n\r"):
        raise DeployError("Systemd unit value contains an invalid control character")
    return '"' + value.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'


def resolved_job_command(repo: Path, command: list[str]) -> list[str]:
    executable = Path(command[0]).expanduser()
    if not executable.is_absolute():
        executable = repo / executable
    return [str(executable.resolve()), *command[1:]]


def render_scheduled_units(app: dict[str, Any], job: dict[str, Any]) -> tuple[str, str, str, str]:
    repo = Path(app["repo_path"]).expanduser().resolve()
    service_name, timer_name = unit_names(app["name"], job["name"])
    description = job.get("description") or f"{app['name']} scheduled job {job['name']}"
    if any(character in description for character in "\x00\n\r"):
        raise DeployError(f"{app['name']}/{job['name']} description contains an invalid control character")
    environment_file = job.get("environment_file", app.get("environment_file"))
    service_lines = [
        MANAGED_UNIT_MARKER, "[Unit]", f"Description={description.replace('%', '%%')}", "", "[Service]",
        "Type=oneshot", f"WorkingDirectory={systemd_quote(str(repo))}",
    ]
    if environment_file:
        service_lines.append(f"EnvironmentFile={systemd_quote(str(Path(environment_file).expanduser().resolve()))}")
    command = resolved_job_command(repo, argument_list(job["command"], "scheduled job command"))
    service_lines.append("ExecStart=" + " ".join(systemd_quote(part) for part in command))
    service = "\n".join(service_lines) + "\n"
    timer = "\n".join([
        MANAGED_UNIT_MARKER, "[Unit]", f"Description=Schedule {description.replace('%', '%%')}", "", "[Timer]",
        f"OnCalendar={schedule_to_on_calendar(job)}",
        f"Persistent={'true' if job.get('persistent', True) else 'false'}",
        f"Unit={service_name}", "", "[Install]", "WantedBy=timers.target", "",
    ])
    return service_name, timer_name, service, timer


def user_unit_directory() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    return (Path(config_home).expanduser() if config_home else Path.home() / ".config") / "systemd" / "user"


def write_if_changed(path: Path, content: str) -> bool:
    try:
        if path.read_text() == content:
            return False
    except FileNotFoundError:
        pass
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content)
    temporary.replace(path)
    return True


def systemctl_ok(arguments: list[str]) -> bool:
    try:
        result = subprocess.run(["systemctl", "--user", *arguments], text=True, capture_output=True,
                                timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def scheduled_job_status(app: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    service_name, timer_name = unit_names(app["name"], job["name"])
    status: dict[str, Any] = {
        "name": job["name"], "enabled": bool(app.get("enabled") and job.get("enabled", True)),
        "schedule": schedule_to_on_calendar(job), "service_unit": service_name, "timer_unit": timer_name,
        "timer_active": False, "next_run": None, "previous_run": None, "result": None,
    }
    if not status["enabled"]:
        return status
    try:
        output = run(["systemctl", "--user", "show", timer_name,
                      "--property=ActiveState,NextElapseUSecRealtime,LastTriggerUSec"], timeout=30)
        properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        status.update(timer_active=properties.get("ActiveState") == "active",
                      next_run=properties.get("NextElapseUSecRealtime") or None,
                      previous_run=properties.get("LastTriggerUSec") or None)
        service_output = run(["systemctl", "--user", "show", service_name, "--property=Result"], timeout=30)
        service_properties = dict(line.split("=", 1) for line in service_output.splitlines() if "=" in line)
        status["result"] = service_properties.get("Result") or None
    except DeployError as exc:
        status["status_error"] = str(exc)
    return status


def reconcile_scheduled_jobs(config: dict[str, Any], logger: logging.Logger,
                             unit_dir: Path | None = None) -> dict[str, list[str]]:
    unit_dir = unit_dir or user_unit_directory()
    unit_dir.mkdir(parents=True, exist_ok=True)
    desired: dict[str, str] = {}
    desired_timers: set[str] = set()
    changed_timers: set[str] = set()
    for app in config["applications"]:
        if not app.get("enabled", False):
            continue
        for job in app.get("scheduled_jobs", []):
            if not job.get("enabled", True):
                continue
            service_name, timer_name, service, timer = render_scheduled_units(app, job)
            desired[service_name], desired[timer_name] = service, timer
            desired_timers.add(timer_name)
    changed: list[str] = []
    removed: list[str] = []
    for name, content in desired.items():
        if write_if_changed(unit_dir / name, content):
            changed.append(name)
            if name.endswith(".timer"):
                changed_timers.add(name)
            logger.info("updated scheduled-job unit %s", name)
    for path in [*unit_dir.glob("uda-*.service"), *unit_dir.glob("uda-*.timer")]:
        if path.name in desired:
            continue
        try:
            managed = path.read_text().startswith(MANAGED_UNIT_MARKER)
        except OSError:
            managed = False
        if not managed:
            continue
        if path.suffix == ".timer":
            systemctl_ok(["disable", "--now", path.name])
        path.unlink()
        removed.append(path.name)
        logger.info("removed obsolete scheduled-job unit %s", path.name)
    if changed or removed:
        run(["systemctl", "--user", "daemon-reload"], timeout=30)
    for timer in sorted(desired_timers):
        enabled = systemctl_ok(["is-enabled", "--quiet", timer])
        active = systemctl_ok(["is-active", "--quiet", timer])
        if not enabled or not active:
            run(["systemctl", "--user", "enable", "--now", timer], timeout=30)
            logger.info("enabled scheduled-job timer %s", timer)
        elif timer in changed_timers:
            run(["systemctl", "--user", "restart", timer], timeout=30)
            logger.info("restarted changed scheduled-job timer %s", timer)
    return {"changed": changed, "removed": removed}


def managed_scheduled_units_exist(unit_dir: Path | None = None) -> bool:
    unit_dir = unit_dir or user_unit_directory()
    if not unit_dir.exists():
        return False
    for path in [*unit_dir.glob("uda-*.service"), *unit_dir.glob("uda-*.timer")]:
        try:
            if path.read_text().startswith(MANAGED_UNIT_MARKER):
                return True
        except OSError:
            continue
    return False


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
    if not app.get("deployment_enabled", True):
        return {"name": name, "status": "service_only"}
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
    restarted = False
    service = app.get("kind", "service") == "service"
    try:
        install_dependencies(app, repo)
        for command in app.get("update_commands", []):
            run([str(part) for part in command], cwd=repo, timeout=int(app.get("command_timeout", 300)))
        if service:
            restarted = True
            run([str(part) for part in app["restart_command"]], timeout=int(app.get("restart_timeout", 60)))
            health_check(str(app["health_url"]), int(app.get("health_timeout", 30)))
    except DeployError as original:
        if app.get("rollback", True):
            logger.exception("%s deployment failed; rolling back to %s", name, previous[:12])
            try:
                git(repo, "reset", "--hard", previous)
                # pip can partially mutate an environment. Never restart until the
                # previous requirements have been restored successfully.
                install_dependencies(app, repo)
                if restarted and service:
                    run([str(part) for part in app["restart_command"]], timeout=int(app.get("restart_timeout", 60)))
                    health_check(str(app["health_url"]), int(app.get("health_timeout", 30)))
            except DeployError as recovery:
                raise DeployError(f"{original}; rollback failed: {recovery}") from original
        raise
    result = {"name": name, "status": "deployed", "from": previous, "to": state["remote"]}
    result["diagnostics"] = diagnostics(app, repo)
    return result


def dependency_command(app: dict[str, Any]) -> list[str] | None:
    """Opt-in Python installs, using each application's existing environment."""
    if not app.get("python"):
        return None
    return [str(Path(app["python"]).expanduser()), "-m", "pip", "install", "--upgrade", "--force-reinstall",
            "-r", str(app.get("requirements", "requirements.txt"))]


def install_dependencies(app: dict[str, Any], repo: Path) -> None:
    command = dependency_command(app)
    if command:
        try:
            run(command, cwd=repo, timeout=int(app.get("command_timeout", 300)))
        except DeployError as exc:
            raise DeployError(f"Dependency installation failed: {exc}") from exc


def diagnostics(app: dict[str, Any], repo: Path) -> dict[str, Any]:
    """Best-effort metadata must not roll back an otherwise healthy deployment."""
    result = {"repository": str(repo), "service": app.get("service_unit"),
              "health": "passed" if app.get("kind", "service") == "service" else "not applicable"}
    if app.get("python"):
        script = """import json, sys, importlib.metadata as m
r = {'virtualenv': sys.prefix, 'python': sys.version}
try:
 d = m.distribution('research-core')
 r['research_core_version'] = d.version
 r['research_core_revision'] = json.loads(d.read_text('direct_url.json') or '{}').get('vcs_info', {}).get('commit_id')
except m.PackageNotFoundError:
 r['research_core_version'] = None
print(json.dumps(r))
"""
        try:
            result.update(json.loads(run([str(Path(app["python"]).expanduser()), "-c", script], cwd=repo)))
        except (DeployError, ValueError) as exc:
            result["python_diagnostic_error"] = str(exc)
    if app.get("health_url"):
        endpoint = urlsplit(app["health_url"])
        port = endpoint.port or (443 if endpoint.scheme == "https" else 80)
        result["port"] = port
        try:
            with socket.create_connection((endpoint.hostname, port), timeout=2):
                result["port_listening"] = True
        except OSError:
            result["port_listening"] = False
    if app.get("service_unit"):
        try:
            result["service_state"] = run(["systemctl", "--user", "is-active", app["service_unit"]])
        except DeployError as exc:
            result["service_state"] = str(exc)
    return result


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


def write_state(config: dict[str, Any], results: list[dict[str, Any]], dry_run: bool,
                partial: bool = False) -> None:
    path = Path(config.get("state_file", "~/.local/state/deployment-agent/status.json")).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if partial and path.exists():
        try:
            existing = json.loads(path.read_text()).get("applications", [])
        except (OSError, json.JSONDecodeError):
            existing = []
        replacements = {item["name"]: item for item in results}
        results = [replacements.pop(item["name"], item) for item in existing]
        results.extend(replacements.values())
    payload = {
        "version": VERSION,
        "last_run": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "ok": not any(item["status"] == "blocked" for item in results),
        "applications": results,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(path)


def execute(config: dict[str, Any], dry_run: bool, verbose: bool,
            application_name: str | None = None) -> list[dict[str, Any]]:
    logger = configure_logging(config, verbose)
    lock_path = Path(config.get("lock_file", "/tmp/deployment-agent.lock")).expanduser()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    results = []
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DeployError("Another deployment-agent run is active") from exc
        applications = config["applications"]
        if application_name is not None:
            applications = [app for app in applications if app["name"] == application_name]
            if not applications:
                raise DeployError(f"Unknown application: {application_name}")
        has_scheduled_jobs = any("scheduled_jobs" in app for app in config["applications"])
        if not dry_run and (has_scheduled_jobs or managed_scheduled_units_exist()):
            reconcile_scheduled_jobs(config, logger)
        for app in applications:
            try:
                result = deploy_application(app, dry_run, logger)
                if "scheduled_jobs" in app:
                    result["scheduled_jobs"] = [scheduled_job_status(app, job)
                                                for job in app.get("scheduled_jobs", [])]
                logger.info("%s: %s", app["name"], result["status"])
            except DeployError as exc:
                result = {"name": app.get("name", "unknown"), "status": "blocked", "error": str(exc)}
                logger.error("%s: %s", result["name"], exc)
            results.append(result)
    write_state(config, results, dry_run, partial=application_name is not None)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely update and restart registered Git applications")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report without changing applications")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--application", help="Only inspect or deploy the named application")
    args = parser.parse_args()
    try:
        results = execute(load_config(args.config), args.dry_run, args.verbose, args.application)
    except DeployError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps({"ok": not any(item["status"] == "blocked" for item in results), "applications": results}, indent=2))
    return 1 if any(item["status"] == "blocked" for item in results) else 0


if __name__ == "__main__":
    sys.exit(main())
