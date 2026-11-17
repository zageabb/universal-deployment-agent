"""UDA v2 semantic graph validator; no deployment operations.

JSON Schema validates shape; this module verifies cross-component references,
DAG topology, canonical ingress and migration policy. It never executes argv.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from datetime import date

import yaml
from jsonschema import Draft202012Validator

SCHEMA = Path(__file__).resolve().parent / "schemas" / "uda-manifest-v2.schema.json"
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class ManifestV2Error(ValueError):
    pass


def _fail(message):
    raise ManifestV2Error(message)


def _topology(edges):
    pending = {node: set(targets) for node, targets in edges.items()}
    ordered = []
    while pending:
        ready = sorted(node for node, targets in pending.items() if not targets)
        if not ready:
            _fail("Deployment graph has a circular service dependency")
        for name in ready:
            ordered.append(name)
            pending.pop(name)
        for targets in pending.values():
            targets.difference_update(ready)
    return ordered


def validate(value):
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    problems = list(validator.iter_errors(value))
    if problems:
        p = sorted(problems, key=lambda x: (str(x.json_path), x.message))[0]
        _fail(f"Schema: {p.json_path}: {p.message}")
    app = value["application"]
    workloads = [*value.get("services", []), *value.get("containers", [])]
    names = [w["name"] for w in workloads]
    if len(names) != len(set(names)):
        _fail("Duplicate service/container names")
    build_names = [item["name"] for item in value.get("builds", [])]
    if len(build_names) != len(set(build_names)):
        _fail("Duplicate build names")
    if set(names).intersection(build_names):
        _fail("A build name conflicts with a service/container name")
    edges = {w["name"]: w.get("depends_on", []) for w in workloads}
    for node, dependencies in edges.items():
        if node in dependencies:
            _fail(f"{node} cannot depend on itself")
        for dependency in dependencies:
            if dependency not in edges:
                _fail(f"Unknown internal dependency {dependency!r} in {node}")
    order = _topology(edges)
    dep_names = [d["name"] for d in value.get("dependencies", [])]
    if len(dep_names) != len(set(dep_names)):
        _fail("Duplicate external dependency names")
    db_names = [d["name"] for d in value.get("databases", [])]
    if len(db_names) != len(set(db_names)):
        _fail("Duplicate database names")
    for database in value.get("databases", []):
        if database.get("managed_by") and database["managed_by"] not in names:
            _fail("Managed database must reference declared service/container")
        if database.get("write_access") == "requires-capability" and not any(
                cap["kind"] == "database-write" and cap.get("target") == database["name"]
                for cap in value.get("capabilities", [])):
            _fail("Write-enabled database requires separately approved database-write capability")
        for migration in database.get("migrations", []):
            if migration["reversible"] and not migration.get("rollback_command"):
                _fail(f"Reversible migration {migration['name']} requires rollback_command")
            if not migration["reversible"] and not migration.get("backup_required"):
                _fail(f"Irreversible migration {migration['name']} requires backup_required")
    proxy = value.get("proxy", {})
    if proxy.get("enabled"):
        if proxy.get("canonical_path", f"/apps/{app['name']}/") != f"/apps/{app['name']}/":
            _fail("Canonical proxy path must match application slug")
        if proxy["upstream"] not in names and not (
                value["deployment"]["strategy"] == "static" and proxy["upstream"] == "static"):
            _fail("Proxy upstream must identify a declared service/container or static artifact")
        if any(w["name"] == proxy["upstream"] and w.get("role") not in (None, "web") for w in workloads):
            _fail("Proxy upstream must be a web-role service or container")
        for alias in proxy.get("aliases", []):
            if alias["path"] == f"/apps/{app['name']}/":
                _fail("Proxy alias duplicates canonical route")
    if app["kind"] == "library" and workloads:
        _fail("Library deployments cannot include running workloads")
    if app["kind"] == "platform" and value["deployment"]["strategy"] != "bootstrap-only":
        _fail("Platform self-management must use bootstrap-only strategy")
    if value["deployment"]["strategy"] == "bootstrap-only" and app["kind"] != "platform":
        _fail("Bootstrap-only strategy is reserved for platform applications")
    if value["deployment"]["strategy"] == "hybrid" and (not value.get("services") or not value.get("containers")):
        _fail("Hybrid strategy requires systemd and container workloads")
    if value["deployment"]["strategy"] == "library" and (workloads or proxy.get("enabled")):
        _fail("Library deployment cannot expose a running service")
    if app["kind"] not in ("library", "platform") and value["deployment"]["strategy"] != "static" and not workloads:
        _fail("Running application must declare its services/containers")
    if value["deployment"]["strategy"] == "static" and not value.get("static"):
        _fail("Static deployment must declare static artifact publication")
    if value["deployment"].get("restart_order"):
        restart_order = value["deployment"]["restart_order"]
        if set(restart_order) != set(names) or len(restart_order) != len(names):
            _fail("restart_order must list all declared workloads once")
        positions = {name: i for i, name in enumerate(restart_order)}
        for name, dependencies in edges.items():
            if any(positions[dep] > positions[name] for dep in dependencies):
                _fail("restart_order violates declared dependencies")
        order = restart_order
    if not (value["deployment"].get("approval") == "explicit"):
        _fail("v2 requires explicit deployment approval")
    declared_secrets = set(value.get("environment", {}).get("required", []))
    used_secrets = set()
    for workload in workloads:
        used_secrets.update(workload.get("environment_refs", []))
    for database in value.get("databases", []):
        if database.get("connection_secret"):
            used_secrets.add(database["connection_secret"])
        used_secrets.update(database.get("connection_refs", []))
    for assertion in proxy.get("assertions", []):
        used_secrets.add(assertion["secret_ref"])
    missing_secrets = used_secrets - declared_secrets
    if missing_secrets:
        _fail("Secret/config references must be declared in environment.required: "
              + ", ".join(sorted(missing_secrets)))
    for container in value.get("containers", []):
        if container.get("image") and not re.fullmatch(
                r"[^\s@]+@sha256:[0-9a-f]{64}", container["image"]):
            _fail(f"Container {container['name']} image must be digest-pinned")
        if not container.get("image") and container.get("build", {}).get("provenance") != "pinned-source-commit":
            _fail(f"Container {container['name']} local build must declare pinned-source-commit provenance")
        mounts = container.get("volumes", [])
        if len({m["name"] for m in mounts}) != len(mounts):
            _fail("Duplicate container volume names")
        for mount in mounts:
            if mount["kind"] == "bind" and mount.get("source", "").startswith("/"):
                _fail("Host absolute bind paths are not allowed in v2")
            if mount["kind"] == "bind" and "source" not in mount:
                _fail("Bind mounts require repo-relative source")
    for dependency in value.get("dependencies", []):
        if dependency["kind"] == "database" and dependency.get("target") not in db_names:
            _fail("Database dependency target must name a declared database")
        if dependency["kind"] == "service" and dependency.get("target") not in names:
            _fail("Service dependency target must name a declared workload")
    # A named health policy is mandatory for multi-process applications so
    # an API returning 200 never silently hides a failed worker.
    health = value.get("health", {})
    if len(workloads) > 1 and not health:
        _fail("Multi-workload deployments require aggregate health policy")
    required_health = health.get("required_services", [])
    optional_health = health.get("optional_services", [])
    if set(required_health).intersection(optional_health):
        _fail("Health required_services and optional_services overlap")
    if health and set(required_health + optional_health) != set(names):
        _fail("Health policy must classify every declared workload")
    for workload in workloads:
        if workload["name"] in required_health + optional_health and not workload.get("health"):
            _fail(f"Required/monitored workload {workload['name']} has no health probe")
        for build in workload.get("required_builds", []):
            if build not in build_names:
                _fail(f"Workload {workload['name']} requires undeclared build {build}")
    routes = proxy.get("routes", [])
    if routes and not proxy.get("enabled"):
        _fail("Proxy subpath routes require enabled authenticated proxy")
    if len({route["subpath"] for route in routes}) != len(routes):
        _fail("Duplicate proxy subpath route")
    for route in routes:
        if route["upstream"] not in names:
            _fail("Proxy route references undeclared upstream")
        if route["authentication"] != "uda":
            _fail("Proxy route must use UDA authentication")
    capabilities = value.get("capabilities", [])
    capability_names = [capability["name"] for capability in capabilities]
    if len(capability_names) != len(set(capability_names)):
        _fail("Duplicate capability names")
    for capability in capabilities:
        if capability["kind"] in ("network-discovery", "router-polling", "database-write"):
            if not capability.get("target"):
                _fail(f"Capability {capability['name']} needs reviewed target")
        if capability["kind"] == "network-discovery" and not capability.get("scope", {}).get("cidr_refs"):
            _fail("Network discovery requires scoped CIDR config references")
    configured = set(value.get("environment", {}).get("required", []))
    definitions = value.get("environment", {}).get("definitions", [])
    if len({entry["name"] for entry in definitions}) != len(definitions):
        _fail("Duplicate typed environment definitions")
    if any(entry["name"] not in configured for entry in definitions):
        _fail("Typed environment definitions must be declared in required")
    new_used = set()
    for build in value.get("builds", []):
        new_used.update(build.get("environment_refs", []))
        new_used.update(build.get("config_refs", []))
    for workload in workloads:
        new_used.update(workload.get("config_refs", []))
    for migration_db in value.get("databases", []):
        for migration in migration_db.get("migrations", []):
            new_used.update(migration.get("environment_refs", []))
            if migration.get("application_compatibility") == "forward-only" and migration.get("rollback_confidence") != "manual-recovery-required":
                _fail("Forward-only migrations require manual-recovery-required rollback")
            if migration.get("seed_policy") == "explicit" and migration.get("idempotency") is None:
                _fail("Explicit seed policy requires migration idempotency review")
    for capability in capabilities:
        for ref_list in capability.get("scope", {}).values():
            new_used.update(ref_list)
    unknown_refs = new_used - configured
    if unknown_refs:
        _fail("Build/runtime/capability config references must be declared: "
              + ", ".join(sorted(unknown_refs)))
    lifecycle = value.get("lifecycle", {})
    if lifecycle:
        if lifecycle["owner"] != app["name"]:
            _fail("Lifecycle owner must match owning application")
        if len(set(lifecycle.get("owned_units", []))) != len(lifecycle.get("owned_units", [])):
            _fail("Duplicate lifecycle-owned units")
    for component in value.get("components", []):
        if component.get("lifecycle_owner") and component["lifecycle_owner"] != app["name"]:
            _fail("Installed component lifecycle owner must match manifest application")
    if app["kind"] == "platform":
        bootstrap = value.get("bootstrap", {})
        if not bootstrap:
            _fail("Protected platform requires external bootstrap supervisor")
        if not value.get("lifecycle"):
            _fail("Protected platform must declare lifecycle owner")
    if app["kind"] == "library" and not value.get("library"):
        _fail("Library deployment requires isolated install and verification policy")
    if proxy.get("aliases"):
        for alias in proxy["aliases"]:
            if not alias.get("expires_on") or not alias.get("mode"):
                _fail("Legacy proxy alias requires mode and retirement date")
            try:
                expiry = date.fromisoformat(alias["expires_on"])
            except ValueError:
                _fail("Alias expiry must be an ISO calendar date")
            if expiry <= date.today():
                _fail("Alias retirement date must be in the future")
    for container in value.get("containers", []):
        for mount in container.get("volumes", []):
            if not mount.get("owner") or not mount.get("backup_policy") or not mount.get("restore_policy"):
                _fail("Persistent volume requires lifecycle owner, backup and restore policies")
    if value.get("static") and value["static"].get("base_path") and value["static"]["base_path"] != f"/apps/{app['name']}/":
        _fail("Static artifact base path must match canonical application slug")
    if value.get("reconciliation"):
        rule = value["reconciliation"]
        if rule.get("reject_undeclared_units") and not rule.get("expected_units"):
            _fail("Unit reconciliation requires inventory of expected units")
    return {"schema_version": 2, "application": app["name"], "deployment_order": order,
            "services": len(value.get("services", [])), "containers": len(value.get("containers", [])),
            "databases": len(value.get("databases", [])), "deployment_allowed": False}


def main():
    if len(sys.argv) != 2:
        _fail("Usage: python standards/uda_manifest_v2_validate.py path/to/uda.yaml")
    data = Path(sys.argv[1]).read_bytes()
    if len(data) > 128 * 1024:
        _fail("uda.yaml v2 exceeds 128 KiB")
    result = validate(yaml.safe_load(data.decode("utf-8")))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
