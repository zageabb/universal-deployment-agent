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



def write_attestation(app: dict, sha: str) -> None:
    """Atomically record a SHA only after the deployment health gate passed.

    Requires an explicitly configured marker path. Never write into a Git tree.
    """
    target = app.get("deployed_sha_file")
    if not target:
        return
    if not SHA.fullmatch(sha):
        raise ValueError("Cannot attest invalid commit SHA")
    path = Path(target).expanduser()
    repo = Path(app["repo_path"]).expanduser().resolve()
    if path.is_symlink() or path.resolve().is_relative_to(repo):
        raise ValueError("Attestation must be outside the repository and not a symlink")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    import tempfile
    try:
        fd, temporary = tempfile.mkstemp(prefix=".uda-sha-", dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(sha + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except OSError as exc:
        raise ValueError(f"Unable to write deployment attestation: {exc}") from exc


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



def publish_once(app: dict, item: dict, token: str, state_path: Path) -> dict:
    """Serialize publications and avoid repeat GitHub events for unchanged releases."""
    import fcntl
    state_path = state_path.expanduser()
    state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            previous = json.loads(state_path.read_text())
        except FileNotFoundError:
            previous = {}
        if not isinstance(previous, dict):
            raise ValueError("Deployment publication state is corrupt")
        key = f"{item.get('repository')}|{item.get('environment', 'production')}"
        # Do not skip validation just because an earlier publication exists.
        if item.get("state") not in {"matched", "behind_remote"}:
            raise ValueError("Refusing publication of unverifiable release")
        if previous.get(key, {}).get("sha") == item.get("running_sha"):
            return {"skipped": "already_published", **previous[key]}
        published = publish_deployment(item, token, app.get("app_url"))
        previous[key] = {"sha": item["running_sha"], "deployment_id": published["deployment_id"],
                         "published_at": datetime.now(timezone.utc).isoformat()}
        import tempfile
        fd, temporary = tempfile.mkstemp(prefix=".uda-publications-", dir=state_path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump(previous, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, state_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return published


def main() -> int:
    from deploy_agent import load_config, health_check
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
                if not app.get("enabled", False):
                    raise ValueError("Application is archived or disabled")
                if app.get("kind", "service") == "service":
                    health_check(str(app["health_url"]), int(app.get("health_timeout", 30)))
                state_path = Path(cfg.get("github_publication_state_file", "~/.local/state/deployment-agent/github-publications.json"))
                item["publication"] = publish_once(app, item, token, state_path)
            except (ValueError, OSError, KeyError) as exc:
                item["publication"] = {"error": str(exc)}
    print(json.dumps(data, indent=2))
    return 1 if args.publish and any(
        "error" in item.get("publication", {}) for item in data["applications"]
        if "publication" in item) else 0


if __name__ == "__main__":
    raise SystemExit(main())
