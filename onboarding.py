"""Repository onboarding discovery and planning. No installation actions are executed.

Only permitted GitHub repository URLs can be inspected. The application manifest
is untrusted data: parsing it must never execute commands, change services or
modify the UDA registry. Installation is a separate, approval-gated operation.
"""
from __future__ import annotations

from pathlib import Path
import re
import os
import json
import base64
import subprocess
import tempfile
from urllib.parse import urlparse, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from typing import Any

import yaml

APP_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
BRANCH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,119}$")
GITHUB_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_MANIFEST_BYTES = 32 * 1024
SUPPORTED_RUNTIME = {"python", "node", "static"}
SUPPORTED_SERVICE = {"systemd", "static"}
SAFE_KEYS = {"schema_version", "application", "source", "runtime", "build",
             "service", "proxy", "deployment", "environment"}


class OnboardingError(ValueError):
    pass


def repository_name(url: str) -> str:
    parsed = urlparse(url.strip())
    if (parsed.scheme != "https" or parsed.hostname != "github.com"
            or parsed.username or parsed.password or parsed.port
            or parsed.query or parsed.fragment):
        raise OnboardingError("Only plain HTTPS github.com repository URLs are accepted")
    repo = parsed.path.strip("/").removesuffix(".git")
    if not GITHUB_REPO.fullmatch(repo):
        raise OnboardingError("Provide a GitHub owner/repository URL")
    return repo


def validate_branch(branch: str) -> str:
    if not isinstance(branch, str) or not BRANCH.fullmatch(branch) or any(value in branch for value in ("..", "//", "@{", "/.", "./")) or branch.endswith((".lock", ".", "/")):
        raise OnboardingError("Invalid Git branch")
    return branch


def _mapping(value: Any, field: str) -> dict:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise OnboardingError(f"{field} must be an object with string keys")
    return value


def _text(value: Any, field: str, limit: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise OnboardingError(f"{field} must be a non-empty string (max {limit})")
    if any(ch in value for ch in "\x00\r\n"):
        raise OnboardingError(f"{field} contains control characters")
    return value.strip()


def validate_manifest(value: Any) -> dict:
    root = _mapping(value, "Manifest")
    unknown = set(root) - SAFE_KEYS
    if unknown:
        raise OnboardingError(f"Unrecognised manifest sections: {', '.join(sorted(unknown))}")
    if type(root.get("schema_version")) is not int or root["schema_version"] != 1:
        raise OnboardingError("schema_version must equal 1")
    source = _mapping(root.get("source", {}), "source")
    if "branch" in source:
        validate_branch(source["branch"])
    application = _mapping(root.get("application"), "application")
    name = _text(application.get("name"), "application.name", 63)
    if not APP_NAME.fullmatch(name):
        raise OnboardingError("application.name must be a safe lowercase slug")
    title = _text(application.get("display_name", name), "application.display_name")
    runtime = _mapping(root.get("runtime"), "runtime")
    kind = runtime.get("type")
    if kind not in SUPPORTED_RUNTIME:
        raise OnboardingError("Unsupported runtime.type")
    service = _mapping(root.get("service"), "service")
    service_type = service.get("type", "static" if kind == "static" else "systemd")
    if service_type not in SUPPORTED_SERVICE:
        raise OnboardingError("Unsupported service.type")
    if kind != "static" and service_type != "systemd":
        raise OnboardingError("Python/Node requires a managed systemd service")
    path = service.get("health_path", "/health")
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path or "\r" in path or "\n" in path:
        raise OnboardingError("health_path must be a local absolute path")
    port = service.get("port", "auto")
    if port != "auto" and (type(port) is not int or not 1024 <= port <= 65535):
        raise OnboardingError("port must be auto or an unprivileged TCP port")
    proxy = _mapping(root.get("proxy", {}), "proxy")
    if "enabled" in proxy and type(proxy["enabled"]) is not bool:
        raise OnboardingError("proxy.enabled must be a boolean")
    if proxy.get("enabled"):
        proxy_path = proxy.get("path", f"/apps/{name}/")
        if proxy_path != f"/apps/{name}/":
            raise OnboardingError("Proxy path must match the canonical application slug")
        if proxy.get("authentication", "uda") != "uda":
            raise OnboardingError("Public/unauthenticated routes cannot be onboarded")
    deployment = _mapping(root.get("deployment", {}), "deployment")
    for key in ("auto_update", "rollback", "github_reporting"):
        if key in deployment and type(deployment[key]) is not bool:
            raise OnboardingError(f"deployment.{key} must be boolean")
    environment = _mapping(root.get("environment", {}), "environment")
    names = environment.get("required", [])
    if not isinstance(names, list) or any(not isinstance(x, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", x) for x in names):
        raise OnboardingError("environment.required must be environment variable names")
    if len(names) != len(set(names)):
        raise OnboardingError("Duplicate environment variable names")
    build = _mapping(root.get("build", {}), "build")
    commands = build.get("commands", [])
    if not isinstance(commands, list) or len(commands) > 20:
        raise OnboardingError("build.commands must contain up to 20 argument arrays")
    for command in commands:
        if not isinstance(command, list) or not (1 <= len(command) <= 30):
            raise OnboardingError("Build commands must be non-empty argument arrays")
        for arg in command:
            _text(arg, "build command argument", 1024)
    entry = service.get("entrypoint", [])
    if service_type == "systemd" and (not isinstance(entry, list) or not entry):
        raise OnboardingError("Managed applications require a service.entrypoint argument array")
    if entry:
        if not isinstance(entry, list) or len(entry) > 30:
            raise OnboardingError("service.entrypoint must be an argument array")
        for arg in entry:
            _text(arg, "service.entrypoint argument", 1024)
    # Repository-authored commands are *never* interpreted as trusted commands.
    # They must go through a second, operator-approved execution policy.
    return {
        "schema_version": 1,
        "name": name, "display_name": title,
        "runtime": kind, "service_type": service_type,
        "port": port, "health_path": path,
        "proxy_enabled": proxy.get("enabled", False),
        "proxy_path": f"/apps/{name}/",
        "required_environment": names,
        "requested_build_commands": commands,
        "requested_entrypoint": entry,
        "auto_update_requested": deployment.get("auto_update", False),
        "github_reporting_requested": deployment.get("github_reporting", False),
        "group": application.get("group"),
    }


def parse_manifest(content: bytes) -> dict:
    if len(content) > MAX_MANIFEST_BYTES:
        raise OnboardingError("Manifest exceeds 32 KiB limit")
    try:
        decoded = content.decode("utf-8")
        value = yaml.safe_load(decoded)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise OnboardingError(f"Cannot parse uda.yaml: {exc}") from exc
    return validate_manifest(value)


def inspect_private_repo(full_name: str, branch: str, token: str) -> dict:
    """Use read-only GitHub API access for private repositories.

    Fetch the chosen branch HEAD first, then load uda.yaml using that exact
    commit SHA so a concurrent branch push cannot swap the manifest.
    """
    if not token:
        raise OnboardingError("GitHub API token is required")
    def read_json(path: str) -> dict:
        url = f"https://api.github.com/repos/{full_name}/{path}"
        request = Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        try:
            with urlopen(request, timeout=15) as response:
                payload = response.read(200_000)
                if len(payload) == 200_000:
                    raise OnboardingError("GitHub API response exceeded size limit")
                return json.loads(payload)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise OnboardingError("GitHub repository or branch could not be read") from exc
    commit = read_json(f"commits/{quote(branch, safe='')}")
    sha = commit.get("sha", "")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise OnboardingError("GitHub did not return a valid commit SHA")
    manifest_data = read_json(f"contents/uda.yaml?ref={sha}")
    if manifest_data.get("encoding") != "base64" or not isinstance(manifest_data.get("content"), str):
        raise OnboardingError("GitHub returned unsupported manifest encoding")
    try:
        raw = base64.b64decode("".join(manifest_data["content"].split()), validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise OnboardingError("GitHub returned invalid manifest data") from exc
    manifest = parse_manifest(raw)
    declared = yaml.safe_load(raw).get("source", {}).get("branch", branch)
    if declared != branch:
        raise OnboardingError("Manifest source.branch differs from selected branch")
    return {"repository": full_name, "branch": branch, "commit_sha": sha,
            "manifest": manifest, "status": "preview_only",
            "requires_approval": True}


def inspect_repo(url: str, branch: str = "main") -> dict:
    full_name = repository_name(url)
    branch = validate_branch(branch)
    token = os.environ.get("UDA_GITHUB_TOKEN", "")
    if token:
        return inspect_private_repo(full_name, branch, token)
    # Read-only discovery. No manifest-defined code runs during this step.
    with tempfile.TemporaryDirectory(prefix="uda-onboard-") as temporary:
        checkout = Path(temporary) / "source"
        remote = f"https://github.com/{full_name}.git"
        cmd = ["git", "-c", "credential.helper=", "clone", "--quiet",
               "--no-checkout", "--depth", "1", "--branch", branch,
               "--", remote, str(checkout)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=90, check=False,
                                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0",
                                         "GCM_INTERACTIVE": "never"})
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OnboardingError("Repository inspection failed or timed out") from exc
        if result.returncode:
            raise OnboardingError("Could not read repository or selected branch")
        def git(*args):
            result = subprocess.run(["git", "-C", str(checkout), *args],
                                    capture_output=True, timeout=15, check=False)
            if result.returncode:
                raise OnboardingError("Repository inspection failed")
            return result.stdout
        sha = git("rev-parse", "HEAD").decode().strip()
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise OnboardingError("Git returned an invalid commit SHA")
        try:
            size = int(git("cat-file", "-s", "HEAD:uda.yaml").decode().strip())
            if size > MAX_MANIFEST_BYTES:
                raise OnboardingError("Manifest exceeds 32 KiB limit")
            data = git("show", "HEAD:uda.yaml")
        except OnboardingError:
            raise OnboardingError("Repository has no root uda.yaml; use discovery mode later")
        manifest = parse_manifest(data)
        declared = yaml.safe_load(data).get("source", {}).get("branch", branch)
        if declared != branch:
            raise OnboardingError("Manifest source.branch differs from selected branch")
        return {"repository": full_name, "branch": branch, "commit_sha": sha,
                "manifest": manifest, "status": "preview_only",
                "requires_approval": True}


def plan_registration(preview: dict, existing: dict) -> dict:
    """Create deterministic preview; NO registry writes or service changes."""
    manifest = preview["manifest"]
    names = {item["name"] for item in existing.get("applications", [])}
    if manifest["name"] in names:
        raise OnboardingError("Application name is already registered")
    occupied = {item.get("service_unit") for item in existing.get("applications", [])}
    unit = f"uda-{manifest['name']}.service"
    if unit in occupied:
        raise OnboardingError("Conflicting service unit")
    ports = {item.get("port") for item in existing.get("applications", [])}
    if isinstance(manifest["port"], int) and manifest["port"] in ports:
        raise OnboardingError("Requested port is already registered")
    return {"repository": preview["repository"], "branch": preview["branch"],
            "commit_sha": preview["commit_sha"], "application": manifest["name"],
            "service_unit": unit if manifest["service_type"] == "systemd" else None,
            "port": manifest["port"], "proxy_path": manifest["proxy_path"]
            if manifest["proxy_enabled"] else None,
            "required_environment": manifest["required_environment"],
            "build_commands_pending_approval": manifest["requested_build_commands"],
            "entrypoint_pending_approval": manifest["requested_entrypoint"],
            "operation": "preview_only", "registry_modified": False,
            "service_modified": False}
