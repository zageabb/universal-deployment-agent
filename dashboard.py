#!/usr/bin/env python3
"""Local management dashboard for the universal deployment agent."""
from __future__ import annotations

import argparse
import fcntl
from datetime import datetime, timezone
import json
import os
import secrets
from pathlib import Path
import subprocess
from threading import Lock
from urllib.request import urlopen

from flask import Flask, abort, redirect, render_template, request, url_for, Response

from deploy_agent import VERSION, DeployError, load_config, reconcile_scheduled_jobs, scheduled_job_status, unit_names
from repo_visibility import resolved_repo_visibility
from deployment_reporting import inventory, inventory_item
from onboarding import inspect_repo, OnboardingError
from onboarding_v2 import preview_v2
from onboarding_install import prepare_plan, issue_ticket, approved_stage
from approval_centre import ACTIONS as APPROVAL_ACTIONS, ApprovalError, create_request, decide, overview, read_only_approval_notice
from tools.validate_v2_only import REVIEW_GATES as V2_REVIEW_GATES
from tools.v2_design_holds import DESIGN_ONLY_HOLDS
from ui_groups import DEFAULT_GROUP, application_group, application_proxy_group, clean_group_name, configured_groups, group_summary

SERVICE_ACTIONS = {"start", "stop", "restart"}


def create_app(config_path: Path) -> Flask:
    app = Flask(__name__)
    app.config["DEPLOY_CONFIG"] = config_path
    app.config["CSRF_TOKEN"] = secrets.token_urlsafe(32)
    app.config["ONBOARDING_APPROVAL_KEY"] = secrets.token_bytes(32)
    config_write_lock = Lock()

    def config():
        return load_config(app.config["DEPLOY_CONFIG"])

    def save_config(cfg: dict) -> None:
        """Validate and atomically replace the registry without widening its permissions."""
        path = Path(app.config["DEPLOY_CONFIG"])
        try:
            mode = path.stat().st_mode & 0o777
            temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            try:
                with os.fdopen(fd, "w") as handle:
                    json.dump(cfg, handle, indent=2)
                    handle.write("\n")
                os.chmod(temporary, mode)
                load_config(temporary)
                os.replace(temporary, path)
            finally:
                if temporary.exists():
                    temporary.unlink()
        except (OSError, DeployError) as exc:
            app.logger.error("Could not update deployment registry: %s", exc)
            abort(500, "Could not update the application registry")

    def mutate_config(mutator):
        with config_write_lock:
            cfg = config()
            mutator(cfg)
            save_config(cfg)
            return cfg

    def state(cfg):
        path = Path(cfg.get("state_file", "~/.local/state/deployment-agent/status.json")).expanduser()
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {"last_run": None, "applications": []}

    def health(url: str) -> dict:
        started = datetime.now(timezone.utc)
        try:
            with urlopen(url, timeout=2) as response:
                healthy = 200 <= response.status < 300
                detail = f"HTTP {response.status}"
        except Exception as exc:
            healthy, detail = False, str(exc)
        elapsed = round((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        return {"healthy": healthy, "detail": detail, "latency_ms": elapsed}

    def service_status(unit: str | None) -> dict | None:
        if not unit:
            return None
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", "--", unit],
                text=True, capture_output=True, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"unit": unit, "state": "unknown", "active": False}
        state_value = (result.stdout or result.stderr).strip() or "unknown"
        return {"unit": unit, "state": state_value, "active": result.returncode == 0}

    def submitted_group_name() -> str:
        try:
            name = clean_group_name(request.form.get("name"))
        except ValueError as exc:
            abort(400, str(exc))
        if name.casefold() == DEFAULT_GROUP.casefold():
            abort(400, f"{DEFAULT_GROUP} is reserved for ungrouped applications")
        return name

    @app.before_request
    def require_auth():
        if request.endpoint == "dashboard_health":
            return None
        expected = config().get("dashboard_token")
        supplied = request.authorization
        if not expected or not supplied or supplied.username != "admin" or supplied.password != expected:
            return Response("Authentication required", 401,
                            {"WWW-Authenticate": 'Basic realm="Deployment Agent"'})
        if request.method == "POST":
            token = request.form.get("csrf_token", "")
            if not secrets.compare_digest(token.encode(), app.config["CSRF_TOKEN"].encode()):
                abort(403, "Refresh the dashboard and try again")
        return None

    @app.get("/")
    def index():
        cfg = config()
        previous = state(cfg)
        prior_by_name = {item["name"]: item for item in previous.get("applications", [])}
        applications = []
        for item in cfg["applications"]:
            applications.append(item | {
                "group": application_group(item),
                "repo_visibility": resolved_repo_visibility(item),
                "deployment_inventory": inventory_item(item),
                "last_result": prior_by_name.get(item["name"]),
                "health": health(str(item["health_url"])) if item.get("enabled") and item.get("health_url") else None,
                "service": service_status(item.get("service_unit")),
                "scheduled_job_statuses": [scheduled_job_status(item, job)
                                           for job in item.get("scheduled_jobs", [])],
            })
        return render_template("dashboard.html", version=VERSION, state=previous,
                               applications=applications,
                               groups=group_summary(applications, configured_groups(cfg)),
                               message=request.args.get("message"),
                               csrf_token=app.config["CSRF_TOKEN"])

    @app.get("/groups")
    def manage_groups():
        cfg = config()
        groups = configured_groups(cfg)
        summary = {row["name"]: row["count"]
                   for row in group_summary(cfg["applications"], groups, include_empty=True)}
        managed = [{"name": name, "count": summary.get(name, 0),
                    "first": index == 0, "last": index == len(groups) - 1}
                   for index, name in enumerate(groups)]
        applications = sorted(
            [{"name": entry["name"],
              "title": entry.get("display_name") or entry["name"],
              "group": application_group(entry),
              "proxy_group": application_proxy_group(entry)}
             for entry in cfg["applications"]],
            key=lambda item: item["title"].casefold(),
        )
        return render_template("groups.html", version=VERSION, groups=managed,
                               ungrouped_count=summary.get(DEFAULT_GROUP, 0),
                               applications=applications, default_group=DEFAULT_GROUP,
                               message=request.args.get("message"),
                               csrf_token=app.config["CSRF_TOKEN"])

    @app.post("/groups/create")
    def create_group():
        name = submitted_group_name()

        def mutate(cfg):
            groups = configured_groups(cfg)
            if any(existing.casefold() == name.casefold() for existing in groups):
                abort(409, "A group with that name already exists")
            cfg["groups"] = [*groups, name]

        mutate_config(mutate)
        return redirect(url_for("manage_groups", message=f"Created group: {name}"))

    @app.post("/groups/rename")
    def rename_group():
        old_name = request.form.get("old_name", "")
        new_name = submitted_group_name()

        def mutate(cfg):
            groups = configured_groups(cfg)
            if old_name not in groups:
                abort(404)
            if any(existing != old_name and existing.casefold() == new_name.casefold()
                   for existing in groups):
                abort(409, "A group with that name already exists")
            cfg["groups"] = [new_name if item == old_name else item for item in groups]
            for entry in cfg["applications"]:
                if application_group(entry) == old_name:
                    entry["group"] = new_name
                if entry.get("proxy_group") == old_name:
                    entry["proxy_group"] = new_name

        mutate_config(mutate)
        return redirect(url_for("manage_groups", message=f"Renamed {old_name} to {new_name}"))

    @app.post("/groups/delete")
    def delete_group():
        name = request.form.get("name", "")

        def mutate(cfg):
            groups = configured_groups(cfg)
            if name not in groups:
                abort(404)
            cfg["groups"] = [item for item in groups if item != name]
            for entry in cfg["applications"]:
                if application_group(entry) == name:
                    entry.pop("group", None)
                if entry.get("proxy_group") == name:
                    entry.pop("proxy_group", None)

        mutate_config(mutate)
        return redirect(url_for("manage_groups", message=f"Deleted {name}; its applications moved to {DEFAULT_GROUP}"))

    @app.post("/groups/reorder")
    def reorder_group():
        name = request.form.get("name", "")
        direction = request.form.get("direction", "")
        if direction not in {"up", "down"}:
            abort(400, "direction must be up or down")

        def mutate(cfg):
            groups = configured_groups(cfg)
            if name not in groups:
                abort(404)
            index = groups.index(name)
            target = index - 1 if direction == "up" else index + 1
            if 0 <= target < len(groups):
                groups[index], groups[target] = groups[target], groups[index]
            cfg["groups"] = groups

        mutate_config(mutate)
        return redirect(url_for("manage_groups", message=f"Updated group order: {name}"))

    @app.post("/applications/<name>/group")
    def assign_group(name: str):
        selected_group = request.form.get("group", "")

        def mutate(cfg):
            selected = next((item for item in cfg["applications"] if item["name"] == name), None)
            if selected is None:
                abort(404)
            groups = configured_groups(cfg)
            cfg["groups"] = groups
            if not selected_group or selected_group == DEFAULT_GROUP:
                selected.pop("group", None)
            else:
                target = next((item for item in groups if item == selected_group), None)
                if target is None:
                    abort(400, "Unknown group")
                selected["group"] = target

        mutate_config(mutate)
        label = selected_group or DEFAULT_GROUP
        return redirect(url_for("manage_groups", message=f"{name} moved to {label}"))

    @app.post("/applications/<name>/proxy-group")
    def assign_proxy_group(name: str):
        selected_group = request.form.get("group", "")

        def mutate(cfg):
            selected = next((item for item in cfg["applications"] if item["name"] == name), None)
            if selected is None:
                abort(404)
            groups = configured_groups(cfg)
            cfg["groups"] = groups
            if not selected_group:
                selected.pop("proxy_group", None)
            else:
                target = next((item for item in groups if item == selected_group), None)
                if target is None:
                    abort(400, "Unknown group")
                selected["proxy_group"] = target

        mutate_config(mutate)
        label = selected_group or "same as UDA group"
        return redirect(url_for("manage_groups", message=f"{name} portal group set to {label}"))

    def approval_store() -> Path:
        cfg = config()
        configured = cfg.get("approval_centre_store")
        return (Path(configured).expanduser() if configured
                else Path(app.config["DEPLOY_CONFIG"]).resolve().parent / "approvals.sqlite3")

    @app.get("/approvals")
    def approvals_index():
        try:
            requests, events = overview(approval_store())
        except Exception as exc:
            # Don't expose storage details or accidentally turn errors into
            # permission to proceed. Existing dashboard stays available.
            app.logger.error("Approval Centre unavailable: %s", type(exc).__name__)
            abort(503, "Approval Centre storage unavailable")
        return render_template(
            "approvals.html", requests=requests, events=events,
            apps=sorted((item["name"] for item in config()["applications"])),
            action_types=sorted(APPROVAL_ACTIONS),
            design_only_holds=DESIGN_ONLY_HOLDS,
            known_v2_gates=sorted(
                ({"repository": name, "gates": gates}
                 for name, gates in V2_REVIEW_GATES.items()),
                key=lambda row: row["repository"].casefold(),
            ),
            csrf_token=app.config["CSRF_TOKEN"],
            notice=read_only_approval_notice(),
            message=request.args.get("message"),
        )

    @app.post("/approvals/request")
    def approvals_request():
        application = request.form.get("application", "")
        if application not in {item["name"] for item in config()["applications"]}:
            abort(400, "Only registered applications may request approval")
        try:
            ttl_hours = int(request.form.get("ttl_hours", "24"))
            ident = create_request(
                approval_store(), application=application,
                action=request.form.get("action", ""),
                scope=request.form.get("scope", ""),
                source_sha=request.form.get("source_sha", ""),
                reason=request.form.get("reason", ""),
                ttl_hours=ttl_hours,
            )
        except (ValueError, ApprovalError) as exc:
            abort(400, str(exc))
        except Exception:
            abort(503, "Approval Centre storage unavailable")
        return redirect(url_for("approvals_index", message="Review request recorded: " + ident[:8]))

    @app.post("/approvals/<ident>/decision")
    def approvals_decide(ident: str):
        try:
            decide(approval_store(), ident, decision=request.form.get("decision", ""),
                   reason=request.form.get("reason", ""))
        except ApprovalError as exc:
            abort(409, str(exc))
        except (OSError, Exception):
            abort(503, "Approval Centre storage unavailable")
        return redirect(url_for("approvals_index", message="Review decision recorded"))

    @app.get("/onboarding")
    def onboarding_form():
        return render_template("onboarding.html", csrf_token=app.config["CSRF_TOKEN"],
                               repository_url="", branch="main", plan=None, v2_plan=None, ticket=None,
                               staged=None, error=None)

    @app.post("/onboarding/preview")
    def onboarding_preview():
        repository_url = request.form.get("repository_url", "").strip()
        branch = request.form.get("branch", "main").strip()
        try:
            preview = inspect_repo(repository_url, branch)
            if preview["manifest"]["schema_version"] == 2:
                # No signed stage ticket, port allocation, registry mutation
                # or executable command handling on the v2 read-only path.
                v2_plan = preview_v2(preview, config())
                plan, ticket = None, None
            else:
                plan = prepare_plan(preview, config())
                ticket = issue_ticket(plan, app.config["ONBOARDING_APPROVAL_KEY"])
                v2_plan = None
            error = None
        except OnboardingError as exc:
            plan, ticket, v2_plan, error = None, None, None, str(exc)
        return render_template("onboarding.html", csrf_token=app.config["CSRF_TOKEN"],
                               repository_url=repository_url, branch=branch,
                               plan=plan, v2_plan=v2_plan, ticket=ticket, staged=None,
                               error=error), (400 if error else 200)

    @app.post("/onboarding/stage")
    def onboarding_stage():
        ticket = request.form.get("approval_ticket", "")
        cfg = config()
        lock_path = Path(cfg.get("lock_file", "/tmp/deployment-agent.lock")).expanduser()
        staging_root = Path(cfg.get("onboarding_staging_root",
                                      "~/.local/state/deployment-agent/onboarding-staging")).expanduser()
        try:
            # Prevent an approved operation racing a running deployment or a second stage.
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    abort(409, "A deployment or onboarding operation is already running")
                staging_root.mkdir(mode=0o700, parents=True, exist_ok=True)
                staged = approved_stage(ticket, app.config["ONBOARDING_APPROVAL_KEY"],
                                        config(), staging_root)
            error = None
        except (OnboardingError, OSError) as exc:
            staged, error = None, str(exc)
        return render_template("onboarding.html", csrf_token=app.config["CSRF_TOKEN"],
                               repository_url="", branch="main", plan=None, v2_plan=None, ticket=None,
                               staged=staged, error=error), (400 if error else 200)

    @app.get("/api/deployments")
    def deployment_inventory_api():
        """Authenticated read-only deployment inventory for future UDA clients."""
        return inventory(config())

    @app.get("/health")
    def dashboard_health():
        return {"ok": True, "version": VERSION}

    @app.post("/applications/<name>/update")
    def update(name: str):
        cfg = config()
        selected = next((item for item in cfg["applications"] if item["name"] == name), None)
        if selected is None:
            abort(404)
        if not selected.get("enabled") or not selected.get("auto_deploy") or not selected.get("deployment_enabled", True):
            abort(403, "Application is not authorized for automatic deployment")
        command = [str(Path(__file__).with_name("deploy_agent.py")), "--config",
                   str(app.config["DEPLOY_CONFIG"]), "--application", name]
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=600, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            app.logger.warning("Manual update for %s could not complete: %s", name, type(exc).__name__)
            return redirect(url_for("index", message=f"{name}: update failed; inspect deployment logs"))
        message = f"{name}: update completed" if result.returncode == 0 else f"{name}: update failed"
        return redirect(url_for("index", message=message))

    @app.post("/applications/<name>/service/<action>")
    def service_action(name: str, action: str):
        cfg = config()
        selected = next((item for item in cfg["applications"] if item["name"] == name), None)
        if selected is None:
            abort(404)
        if action not in SERVICE_ACTIONS:
            abort(404)
        unit = selected.get("service_unit")
        if not selected.get("enabled") or not unit:
            abort(403, "Application service control is not enabled in the registry")
        try:
            lock_path = Path(cfg.get("lock_file", "/tmp/deployment-agent.lock")).expanduser()
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    abort(409, "A deployment or service action is already running")
                result = subprocess.run(
                    ["systemctl", "--user", action, "--", unit],
                    text=True, capture_output=True, timeout=30, check=False,
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return redirect(url_for("index", message=f"{name}: {action} failed: {exc}"))
        if result.returncode == 0:
            message = f"{name}: {action} completed"
        else:
            detail = (result.stderr or result.stdout).strip()[-300:]
            message = f"{name}: {action} failed: {detail}"
        return redirect(url_for("index", message=message))

    @app.post("/applications/<name>/enabled")
    def set_application_enabled(name: str):
        requested = request.form.get("enabled")
        if requested not in {"true", "false"}:
            abort(400, "enabled must be true or false")
        enabled = requested == "true"
        cfg = config()
        selected = next((item for item in cfg["applications"] if item["name"] == name), None)
        if selected is None:
            abort(404)
        unit = selected.get("service_unit")
        if selected.get("kind", "service") == "service" and not unit:
            abort(409, "Configure service_unit before archiving or restoring this service")
        lock_path = Path(cfg.get("lock_file", "/tmp/deployment-agent.lock")).expanduser()
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    abort(409, "A deployment or service action is already running")
                if unit:
                    verb = "enable" if enabled else "disable"
                    result = subprocess.run(
                        ["systemctl", "--user", verb, "--now", "--", unit],
                        text=True, capture_output=True, timeout=30, check=False,
                    )
                    if result.returncode:
                        detail = (result.stderr or result.stdout).strip()[-300:]
                        action = "restore" if enabled else "archive"
                        return redirect(url_for("index", message=f"{name}: {action} failed: {detail}"))
                with config_write_lock:
                    current = config()
                    current_app = next(
                        (item for item in current["applications"] if item["name"] == name),
                        None,
                    )
                    if current_app is None:
                        abort(404)
                    current_app["enabled"] = enabled
                    save_config(current)
                try:
                    reconcile_scheduled_jobs(current, app.logger)
                except (DeployError, OSError, subprocess.SubprocessError) as exc:
                    app.logger.exception("Could not reconcile scheduled jobs after changing %s", name)
                    action = "restored" if enabled else "archived"
                    message = f"{name}: {action}, but scheduled jobs need attention: {exc}"
                    return redirect(url_for("index", message=message))
                suffix = ""
                if selected.get("proxy_enabled"):
                    try:
                        refresh = subprocess.run(
                            ["systemctl", "--user", "start", "uda-proxy-refresh.service"],
                            text=True, capture_output=True, timeout=120, check=False,
                        )
                        if refresh.returncode:
                            app.logger.warning(
                                "Proxy refresh failed after changing %s: %s",
                                name,
                                (refresh.stderr or refresh.stdout).strip()[-300:],
                            )
                            suffix = "; proxy refresh needs attention"
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        app.logger.warning("Proxy refresh unavailable for %s: %s", name, type(exc).__name__)
                        suffix = "; proxy refresh needs attention"
        except (OSError, subprocess.TimeoutExpired) as exc:
            action = "restore" if enabled else "archive"
            return redirect(url_for("index", message=f"{name}: {action} failed: {exc}"))
        action = "restored" if enabled else "archived"
        return redirect(url_for("index", message=f"{name}: {action}{suffix}"))

    @app.post("/applications/<name>/scheduled-jobs/<job_name>/run")
    def run_scheduled_job(name: str, job_name: str):
        cfg = config()
        selected = next((item for item in cfg["applications"] if item["name"] == name), None)
        if selected is None:
            abort(404)
        job = next((item for item in selected.get("scheduled_jobs", []) if item["name"] == job_name), None)
        if job is None:
            abort(404)
        if not selected.get("enabled") or not job.get("enabled", True):
            abort(403, "Scheduled job is not enabled in the registry")
        service_unit, _ = unit_names(name, job_name)
        try:
            lock_path = Path(cfg.get("lock_file", "/tmp/deployment-agent.lock")).expanduser()
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    abort(409, "A deployment or service action is already running")
                result = subprocess.run(
                    ["systemctl", "--user", "start", "--", service_unit],
                    text=True, capture_output=True, timeout=600, check=False,
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return redirect(url_for("index", message=f"{name}/{job_name}: run failed: {exc}"))
        if result.returncode == 0:
            message = f"{name}/{job_name}: run completed"
        else:
            detail = (result.stderr or result.stdout).strip()[-300:]
            message = f"{name}/{job_name}: run failed: {detail}"
        return redirect(url_for("index", message=message))

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Universal deployment agent dashboard")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=5030, type=int)
    args = parser.parse_args()
    create_app(args.config).run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
