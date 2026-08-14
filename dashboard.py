#!/usr/bin/env python3
"""Local management dashboard for the universal deployment agent."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from urllib.request import urlopen

from flask import Flask, abort, redirect, render_template, request, url_for, Response

from deploy_agent import VERSION, load_config


def create_app(config_path: Path) -> Flask:
    app = Flask(__name__)
    app.config["DEPLOY_CONFIG"] = config_path

    def config():
        return load_config(app.config["DEPLOY_CONFIG"])

    @app.before_request
    def require_auth():
        if request.endpoint == "dashboard_health":
            return None
        expected = config().get("dashboard_token")
        supplied = request.authorization
        if not expected or not supplied or supplied.username != "admin" or supplied.password != expected:
            return Response("Authentication required", 401,
                            {"WWW-Authenticate": 'Basic realm="Deployment Agent"'})
        return None

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

    @app.get("/")
    def index():
        cfg = config()
        previous = state(cfg)
        prior_by_name = {item["name"]: item for item in previous.get("applications", [])}
        applications = []
        for item in cfg["applications"]:
            applications.append(item | {
                "last_result": prior_by_name.get(item["name"]),
                "health": health(str(item["health_url"])) if item.get("enabled") else None,
            })
        return render_template("dashboard.html", version=VERSION, state=previous,
                               applications=applications, message=request.args.get("message"))

    @app.get("/health")
    def dashboard_health():
        return {"ok": True, "version": VERSION}

    @app.post("/applications/<name>/update")
    def update(name: str):
        cfg = config()
        selected = next((item for item in cfg["applications"] if item["name"] == name), None)
        if selected is None:
            abort(404)
        if not selected.get("enabled") or not selected.get("auto_deploy"):
            abort(403, "Application is not authorized for automatic deployment")
        command = [str(Path(__file__).with_name("deploy_agent.py")), "--config",
                   str(app.config["DEPLOY_CONFIG"]), "--application", name]
        result = subprocess.run(command, text=True, capture_output=True, timeout=600, check=False)
        message = f"{name}: update completed" if result.returncode == 0 else f"{name}: update failed"
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
