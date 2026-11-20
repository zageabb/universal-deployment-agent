"""Read-only, version-aware UDA deployment manifest inspection.

V1 retains its original parser and stage-only flow. V2 produces *only* an
operator review plan; it cannot issue a staging ticket or activate anything.
"""
from __future__ import annotations

import re
from typing import Any

import yaml

from onboarding import OnboardingError, MAX_MANIFEST_BYTES, parse_manifest
from uda_manifest_v2_validate import ManifestV2Error, validate as validate_v2


def parse_versioned_manifest(raw: bytes) -> dict:
    """Select only explicitly supported versions; preserve v1 semantics."""
    if not isinstance(raw, bytes) or len(raw) > 128 * 1024:
        raise OnboardingError("Manifest exceeds v2 size limit (128 KiB)")
    try:
        value = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise OnboardingError("Invalid uda.yaml syntax") from exc
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
        raise OnboardingError("Manifest must declare an integer schema_version")
    version = value["schema_version"]
    if version == 1:
        # Preserve the smaller v1 size limit and all legacy validation.
        if len(raw) > MAX_MANIFEST_BYTES:
            raise OnboardingError("Manifest exceeds 32 KiB limit")
        return parse_manifest(raw)
    if version != 2:
        raise OnboardingError("Unsupported uda.yaml schema_version; no deployment permitted")
    try:
        validate_v2(value)
    except ManifestV2Error as exc:
        raise OnboardingError(f"Invalid v2 uda.yaml: {exc}") from exc
    # Keep validated graph available only inside the trusted server process;
    # do NOT send authored commands, secrets or arbitrary source fields to UI.
    return value


def _port(value: Any) -> int | str | None:
    if type(value) is int:
        return value
    if value == "auto":
        return "auto"
    return None


def _service_summary(item: dict, container: bool) -> dict:
    mapping = {
        "name": item["name"],
        "kind": "container" if container else "systemd",
        "role": item.get("role", "container" if container else "worker"),
        "runtime": item.get("runtime") if not container else "container",
        "working_dir": item.get("working_dir", "."),
        "depends_on": list(item.get("depends_on", [])),
        "health": item.get("health", {}).get("type", "not-declared"),
        "port": _port(item.get("port")) if not container else
                [_port(port.get("host_port")) for port in item.get("ports", [])],
        "required_builds": list(item.get("required_builds", [])),
    }
    return mapping


def preview_v2(preview: dict, registry: dict) -> dict:
    """Return a bounded, redacted plan and conflicts, never an executable plan."""
    doc = preview.get("manifest")
    if not isinstance(doc, dict) or doc.get("schema_version") != 2:
        raise OnboardingError("v2 preview requires a v2 manifest")
    try:
        validate_v2(doc)
    except ManifestV2Error as exc:
        raise OnboardingError(f"Invalid v2 uda.yaml: {exc}") from exc
    source = doc.get("source", {})
    if source.get("branch", preview.get("branch")) != preview.get("branch"):
        raise OnboardingError("Manifest source.branch differs from selected branch")
    if source.get("repository") and source["repository"] != preview.get("repository"):
        raise OnboardingError("Manifest source.repository differs from selected repository")
    sha = preview.get("commit_sha")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise OnboardingError("v2 preview requires pinned source commit")
    workloads = [
        *[_service_summary(s, False) for s in doc.get("services", [])],
        *[_service_summary(s, True) for s in doc.get("containers", [])],
    ]
    registry_apps = registry.get("applications", [])
    matches = [a for a in registry_apps if a.get("name") == doc["application"]["name"]]
    registry_ports = {
        a.get("port"): a.get("name") for a in registry_apps
        if type(a.get("port")) is int and a.get("name") != doc["application"]["name"]
    }
    conflicts = []
    # Existing registrations are expected in an import scenario: show, don't
    # pretend a replacement is safe. Refuse activation unconditionally.
    if matches:
        conflicts.append("Application already exists in UDA registry; adoption/reconciliation required")
    for item in workloads:
        ports = item["port"] if isinstance(item["port"], list) else [item["port"]]
        for port in ports:
            if type(port) is int and port in registry_ports:
                conflicts.append(f"Port {port} is registered to {registry_ports[port]}")
    if doc.get("reconciliation", {}).get("expected_live_commit"):
        if doc["reconciliation"]["expected_live_commit"] != sha:
            conflicts.append("Expected deployed commit differs from selected GitHub source")
    return {
        "schema_version": 2,
        "repository": preview["repository"],
        "branch": preview["branch"],
        "commit_sha": sha,
        "application": doc["application"]["name"],
        "kind": doc["application"]["kind"],
        "strategy": doc["deployment"]["strategy"],
        "workloads": workloads,
        "builds": [{"name": x["name"], "toolchain": x["toolchain"],
                    "working_dir": x.get("working_dir", ".")}
                   for x in doc.get("builds", [])],
        "dependencies": [{"name": x["name"], "kind": x["kind"],
                          "readiness": x.get("readiness", "not-declared"),
                          "failure_policy": x.get("failure_policy", "not-declared")}
                         for x in doc.get("dependencies", [])],
        "databases": [{"name": x["name"], "engine": x["engine"],
                       "backup": x.get("backup"), "migrations": len(x.get("migrations", []))}
                      for x in doc.get("databases", [])],
        "volumes": [{"name": m["name"], "owner": m.get("owner"),
                     "backup": m.get("backup_policy")}
                    for c in doc.get("containers", [])
                    for m in c.get("volumes", [])],
        "proxy": {
            "enabled": doc.get("proxy", {}).get("enabled", False),
            "path": doc.get("proxy", {}).get("canonical_path"),
            "upstream": doc.get("proxy", {}).get("upstream"),
            "subpath_routes": len(doc.get("proxy", {}).get("routes", [])),
            "assertions": len(doc.get("proxy", {}).get("assertions", [])),
            "aliases": len(doc.get("proxy", {}).get("aliases", [])),
            "authentication": doc.get("proxy", {}).get("authentication"),
        },
        "required_environment_names": list(doc.get("environment", {}).get("required", [])),
        "capabilities": [{"name": x["name"], "kind": x["kind"],
                          "requires_approval": True, "enabled": False}
                         for x in doc.get("capabilities", [])],
        "health": {"aggregate": doc.get("health", {}).get("aggregate"),
                   "required": list(doc.get("health", {}).get("required_services", [])),
                   "optional": list(doc.get("health", {}).get("optional_services", []))},
        "conflicts": sorted(set(conflicts)),
        "approval_required": True,
        "execution_allowed": False,
        "staging_allowed": False,
        "operation": "v2_readonly_preview",
        "blocked_reason": "V2 activation is not supported; review-only until adapters are accepted",
    }
