"""Read-only deployment inventory and opt-in GitHub deployment publishing.

The running artifact must attest its commit SHA independently of the checkout.
Never claim an unverified or dirty checkout is the running build.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

SHA = re.compile(r"^[0-9a-f]{40}$")
OWNER_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
GITHUB_HOSTS = {"github.com", "www.github.com"}


def git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(path), *args],
                            capture_output=True, text=True, timeout=15, check=False)
    if result.returncode:
        raise ValueError("Could not inspect local Git checkout")
    return result.stdout.strip()


def github_repository(origin: str) -> str | None:
    """Accept only github.com origin forms; never use arbitrary URL hosts."""
    origin = origin.strip()
    if origin.startswith("git@github.com:"):
        candidate = origin.partition(":")[2]
    else:
        parsed = urlparse(origin)
        if parsed.scheme not in {"https", "ssh"} or parsed.hostname not in GITHUB_HOSTS:
            return None
        candidate = parsed.path.lstrip("/")
    candidate = candidate.removesuffix(".git").strip("/")
    return candidate if OWNER_REPO.fullmatch(candidate) else None


def inventory_item(app: dict) -> dict:
    item = {"name": app.get("name", ""), "repository": None,
            "checkout_sha": None, "running_sha": None, "remote_sha": None,
            "state": "unknown", "reason": None, "dirty": None,
            "environment": app.get("github_environment", "production")}
    if not app.get("deployment_enabled", True):
        item["state"] = "service_only"
        return item
    path = Path(app["repo_path"]).expanduser().resolve()
    try:
        item["checkout_sha"] = git(path, "rev-parse", "HEAD")
        item["dirty"] = bool(git(path, "status", "--porcelain"))
        item["repository"] = github_repository(git(path, "remote", "get-url", "origin"))
        branch = str(app.get("branch", "main"))
        try:
            item["remote_sha"] = git(path, "rev-parse", "--verify", f"refs/remotes/origin/{branch}")
        except ValueError:
            pass
        attestation = app.get("deployed_sha_file")
        if not attestation:
            item["state"] = "unverified"
            item["reason"] = "No deployed_sha_file configured"
            return item
        sha = Path(attestation).expanduser().read_text(encoding="ascii").strip().lower()
        if not SHA.fullmatch(sha):
            raise ValueError("Invalid deployed SHA attestation")
        item["running_sha"] = sha
        if item["dirty"]:
            item["state"] = "dirty"
            item["reason"] = "Checkout has uncommitted modifications"
        elif sha != item["checkout_sha"]:
            item["state"] = "mismatch"
            item["reason"] = "Running artifact does not match local checkout"
        elif item["remote_sha"] and sha != item["remote_sha"]:
            item["state"] = "behind_remote"
        else:
            item["state"] = "matched"
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        item["state"] = "unknown"
        item["reason"] = str(exc)
    return item


def inventory(config: dict) -> dict:
    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "applications": [inventory_item(app) for app in config["applications"]]}


def publish_deployment(item: dict, token: str, environment_url: str | None = None,
                       api_base: str = "https://api.github.com") -> dict:
    """Publish only a verified clean SHA with a GitHub Deployments API request."""
    if item.get("state") not in {"matched", "behind_remote"}:
        raise ValueError("Refusing to publish unverified, dirty, or mismatched deployment")
    repository = item.get("repository")
    sha = item.get("running_sha")
    if not repository or not OWNER_REPO.fullmatch(repository) or not sha or not SHA.fullmatch(sha):
        raise ValueError("Missing valid GitHub repository or deployed commit SHA")
    if not token:
        raise ValueError("GitHub deployment token is required")
    if environment_url:
        parsed = urlparse(environment_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Environment URL must be absolute HTTPS without embedded credentials")
    if api_base != "https://api.github.com":
        raise ValueError("Only the official GitHub API is allowed")
    url = f"{api_base}/repos/{repository}/deployments"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"}
    payload = {"ref": sha, "environment": item.get("environment", "production"),
               "auto_merge": False, "required_contexts": [], "description": "UDA verified deployed commit"}
    request = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=15) as response:
        deployment = json.load(response)
    deployment_id = deployment["id"]
    status = {"state": "success", "description": "Runtime SHA verified by UDA",
              "auto_inactive": False}
    if environment_url:
        status["environment_url"] = environment_url
    request = Request(f"{url}/{deployment_id}/statuses",
                      data=json.dumps(status).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=15) as response:
        published = json.load(response)
    return {"repository": repository, "deployment_id": deployment_id,
            "sha": sha, "status_id": published["id"]}


def main() -> int:
    from deploy_agent import load_config
    parser = argparse.ArgumentParser(description="Preview or publish verified UDA deployments")
    parser.add_argument("--config", required=True)
    parser.add_argument("--publish", action="store_true",
                        help="Opt in to GitHub writes; default is read-only")
    args = parser.parse_args()
    cfg = load_config(Path(args.config))
    data = inventory(cfg)
    if args.publish:
        token = os.environ.get("UDA_GITHUB_DEPLOYMENT_TOKEN", "")
        for app, item in zip(cfg["applications"], data["applications"]):
            if not app.get("github_reporting_enabled", False):
                continue
            try:
                item["publication"] = publish_deployment(item, token, app.get("app_url"))
            except (ValueError, OSError, KeyError) as exc:
                item["publication"] = {"error": str(exc)}
    print(json.dumps(data, indent=2))
    return 1 if args.publish and any(
        "error" in item.get("publication", {}) for item in data["applications"]
        if "publication" in item) else 0


if __name__ == "__main__":
    raise SystemExit(main())
