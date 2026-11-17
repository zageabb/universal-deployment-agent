"""UDA manifest v2 independent schema + semantic policy checks.

No service, container, migration or shell command is executed.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import unittest
import yaml

from standards.uda_manifest_v2_validate import ManifestV2Error, validate

ROOT = Path(__file__).resolve().parents[1]


def load_example(name):
    return yaml.safe_load((ROOT / "examples" / name).read_text())


class TestUdaManifestV2(unittest.TestCase):
    def test_all_example_manifests_validate(self):
        for path in sorted((ROOT / "examples").glob("uda-v2-*.yaml")):
            with self.subTest(path=path.name):
                result = validate(yaml.safe_load(path.read_text()))
                self.assertEqual(result["schema_version"], 2)
                self.assertFalse(result["deployment_allowed"])

    def test_v1_does_not_accidentally_validate_as_v2(self):
        manifest = load_example("uda-v2-multi-service.yaml")
        manifest["schema_version"] = 1
        with self.assertRaises(ManifestV2Error):
            validate(manifest)

    def test_nested_unknown_fields_are_rejected(self):
        for section, key, value in [
            ("services", "run_as_root", True),
            ("containers", "privileged", True),
            ("proxy", "arbitrary_caddy", "allow all"),
            ("deployment", "auto_execute", True),
        ]:
            with self.subTest(section=section):
                document = load_example("uda-v2-container.yaml" if section == "containers" else "uda-v2-multi-service.yaml")
                target = document[section][0] if isinstance(document[section], list) else document[section]
                target[key] = value
                with self.assertRaises(ManifestV2Error):
                    validate(document)

    def test_circular_service_dependencies_rejected(self):
        document = load_example("uda-v2-multi-service.yaml")
        document["services"][0]["depends_on"] = ["mailbox"]
        with self.assertRaisesRegex(ManifestV2Error, "circular"):
            validate(document)

    def test_missing_internal_service_dependency_rejected(self):
        document = load_example("uda-v2-multi-service.yaml")
        document["services"][1]["depends_on"] = ["missing"]
        with self.assertRaisesRegex(ManifestV2Error, "Unknown internal"):
            validate(document)

    def test_web_proxy_upstream_is_mandatory_and_valid(self):
        document = load_example("uda-v2-multi-service.yaml")
        document["proxy"]["upstream"] = "mailbox"
        with self.assertRaisesRegex(ManifestV2Error, "web-role"):
            validate(document)
        document["proxy"]["upstream"] = "other"
        with self.assertRaisesRegex(ManifestV2Error, "declared"):
            validate(document)

    def test_proxy_cannot_change_canonical_slug(self):
        document = load_example("uda-v2-multi-service.yaml")
        document["proxy"]["canonical_path"] = "/apps/unrelated/"
        with self.assertRaisesRegex(ManifestV2Error, "Canonical"):
            validate(document)

    def test_irreversible_migration_requires_backup(self):
        document = load_example("uda-v2-database.yaml")
        document["databases"][0]["migrations"][0]["backup_required"] = False
        with self.assertRaisesRegex(ManifestV2Error, "backup_required"):
            validate(document)

    def test_reversible_migration_requires_rollback_command(self):
        document = load_example("uda-v2-database.yaml")
        migration = document["databases"][0]["migrations"][0]
        migration["reversible"] = True
        with self.assertRaisesRegex(ManifestV2Error, "rollback_command"):
            validate(document)

    def test_container_image_must_be_digest_pinned(self):
        document = load_example("uda-v2-container.yaml")
        document["containers"][0]["image"] = "docker.io/library/python:latest"
        with self.assertRaisesRegex(ManifestV2Error, "digest-pinned"):
            validate(document)

    def test_no_absolute_host_bind_mount(self):
        document = load_example("uda-v2-container.yaml")
        document["containers"][0]["volumes"] = [
            {"name": "sensitive", "kind": "bind", "source": "/etc",
             "mount_path": "/data", "preserve_data": True}
        ]
        with self.assertRaisesRegex(ManifestV2Error, "Host absolute"):
            validate(document)

    def test_platform_requires_bootstrap_only(self):
        document = load_example("uda-v2-bootstrap.yaml")
        document["deployment"]["strategy"] = "systemd"
        with self.assertRaises(ManifestV2Error):
            validate(document)

    def test_library_is_not_publishable(self):
        document = load_example("uda-v2-library.yaml")
        document["proxy"] = {"enabled": True, "upstream": "anything",
                             "authentication": "uda"}
        with self.assertRaises(ManifestV2Error):
            validate(document)

    def test_restart_order_must_respect_dependencies(self):
        document = load_example("uda-v2-multi-service.yaml")
        document["deployment"]["restart_order"] = ["mailbox", "web"]
        with self.assertRaisesRegex(ManifestV2Error, "restart_order"):
            validate(document)

    def test_undeclared_secret_reference_is_rejected(self):
        document = load_example("uda-v2-container.yaml")
        document["environment"]["required"] = ["SECRET_KEY"]
        with self.assertRaisesRegex(ManifestV2Error, "Secret/config references"):
            validate(document)

    def test_short_image_digest_is_rejected(self):
        document = load_example("uda-v2-container.yaml")
        document["containers"][0]["image"] = "registry.example/app@sha256:abcd"
        with self.assertRaisesRegex(ManifestV2Error, "digest-pinned"):
            validate(document)

    def test_database_dependency_must_target_declared_db(self):
        document = load_example("uda-v2-database.yaml")
        document["dependencies"][0]["target"] = "absent"
        with self.assertRaisesRegex(ManifestV2Error, "declared database"):
            validate(document)

    def test_bind_mount_requires_repo_relative_source(self):
        document = load_example("uda-v2-container.yaml")
        document["containers"][0]["volumes"] = [
            {"name": "data", "kind": "bind", "mount_path": "/data", "preserve_data": True}
        ]
        with self.assertRaisesRegex(ManifestV2Error, "repo-relative source"):
            validate(document)

    def test_multi_service_requires_aggregate_health(self):
        document = load_example("uda-v2-multi-service.yaml")
        del document["health"]
        with self.assertRaisesRegex(ManifestV2Error, "aggregate health"):
            validate(document)

    def test_aggregate_health_classifies_every_service(self):
        document = load_example("uda-v2-multi-service.yaml")
        document["health"]["optional_services"] = []
        with self.assertRaisesRegex(ManifestV2Error, "classify every"):
            validate(document)

    def test_required_worker_cannot_omit_probe(self):
        document = load_example("uda-v2-multi-service.yaml")
        document["health"]["required_services"] = ["web", "mailbox"]
        document["health"]["optional_services"] = []
        del document["services"][1]["health"]
        with self.assertRaisesRegex(ManifestV2Error, "no health probe"):
            validate(document)

    def test_context_studio_asset_subpath_route_is_authenticated(self):
        document = load_example("uda-v2-multi-service.yaml")
        document["proxy"]["routes"] = [{
            "subpath": "assets/", "upstream": "web",
            "prefix_mode": "strip", "authentication": "uda"
        }]
        assert validate(document)["deployment_allowed"] is False
        document["proxy"]["routes"][0]["authentication"] = "none"
        with self.assertRaises(ManifestV2Error):
            validate(document)

    def test_proxy_subpath_cannot_reference_unknown_workload(self):
        document = load_example("uda-v2-multi-service.yaml")
        document["proxy"]["routes"] = [{
            "subpath": "assets/", "upstream": "unregistered",
            "prefix_mode": "strip", "authentication": "uda"
        }]
        with self.assertRaisesRegex(ManifestV2Error, "undeclared upstream"):
            validate(document)

    def test_capability_database_write_requires_explicit_scope(self):
        document = load_example("uda-v2-database.yaml")
        document["capabilities"] = [{
            "name": "database-write", "kind": "database-write",
            "approval": "explicit", "enabled_by_default": False
        }]
        with self.assertRaisesRegex(ManifestV2Error, "reviewed target"):
            validate(document)
        document["capabilities"][0]["target"] = "primary"
        self.assertEqual(validate(document)["schema_version"], 2)
        document["capabilities"][0]["enabled_by_default"] = True
        with self.assertRaises(ManifestV2Error):
            validate(document)

    def test_network_discovery_requires_cidr_ref(self):
        document = load_example("uda-v2-multi-service.yaml")
        document["capabilities"] = [{
            "name": "active-discovery", "kind": "network-discovery",
            "target": "lan", "approval": "explicit",
            "enabled_by_default": False
        }]
        with self.assertRaisesRegex(ManifestV2Error, "scoped CIDR"):
            validate(document)
        document["capabilities"][0]["scope"] = {"cidr_refs": ["DISCOVERY_CIDR"]}
        document["environment"] = {"required": ["DISCOVERY_CIDR"]}
        self.assertFalse(validate(document)["deployment_allowed"])

    def test_build_env_reference_must_be_declared(self):
        document = load_example("uda-v2-multi-service.yaml")
        document["builds"][0]["environment_refs"] = ["NEXT_PUBLIC_BASE_PATH"]
        with self.assertRaisesRegex(ManifestV2Error, "config references"):
            validate(document)
        document["environment"] = {"required": ["NEXT_PUBLIC_BASE_PATH"]}
        self.assertFalse(validate(document)["deployment_allowed"])

    def test_migration_forward_only_needs_manual_recovery(self):
        document = load_example("uda-v2-database.yaml")
        migration = document["databases"][0]["migrations"][0]
        migration["application_compatibility"] = "forward-only"
        migration["rollback_confidence"] = "code-only"
        with self.assertRaisesRegex(ManifestV2Error, "manual-recovery-required"):
            validate(document)
        migration["rollback_confidence"] = "manual-recovery-required"
        self.assertEqual(validate(document)["databases"], 1)

    def test_persistent_volume_requires_backup_owner_and_restore_policy(self):
        document = load_example("uda-v2-container.yaml")
        document["containers"][0]["volumes"][0].pop("backup_policy")
        with self.assertRaisesRegex(ManifestV2Error, "Persistent volume"):
            validate(document)

    def test_local_build_requires_source_provenance(self):
        document = load_example("uda-v2-container.yaml")
        document["containers"][0].pop("image")
        with self.assertRaisesRegex(ManifestV2Error, "pinned-source-commit"):
            validate(document)
        document["containers"][0]["build"]["provenance"] = "pinned-source-commit"
        self.assertFalse(validate(document)["deployment_allowed"])

    def test_library_requires_isolated_install_policy(self):
        document = load_example("uda-v2-library.yaml")
        del document["library"]
        with self.assertRaisesRegex(ManifestV2Error, "isolated install"):
            validate(document)

    def test_platform_requires_bootstrap_and_owner(self):
        document = load_example("uda-v2-bootstrap.yaml")
        del document["bootstrap"]
        with self.assertRaisesRegex(ManifestV2Error, "external bootstrap"):
            validate(document)
        document = load_example("uda-v2-bootstrap.yaml")
        document["lifecycle"]["owner"] = "other-app"
        with self.assertRaisesRegex(ManifestV2Error, "Lifecycle owner"):
            validate(document)

    def test_legacy_alias_needs_expiry_and_mode(self):
        document = load_example("uda-v2-multi-service.yaml")
        document["proxy"]["aliases"] = [{
            "path": "/apps/tender_designer/", "approval": "separate"
        }]
        with self.assertRaisesRegex(ManifestV2Error, "retirement date"):
            validate(document)
        document["proxy"]["aliases"][0].update(
            expires_on="2027-01-31", mode="redirect", asset_base_migration="rebuild-verified")
        self.assertFalse(validate(document)["deployment_allowed"])

    def test_lifecycle_unit_inventory_required_when_reconciliation_enabled(self):
        document = load_example("uda-v2-multi-service.yaml")
        document["reconciliation"] = {"reject_undeclared_units": True}
        with self.assertRaisesRegex(ManifestV2Error, "inventory of expected units"):
            validate(document)
        document["reconciliation"]["expected_units"] = ["tender-web.service", "tender-mailbox.service"]
        self.assertFalse(validate(document)["deployment_allowed"])

    def test_missing_deployment_approval_rejected(self):
        document = load_example("uda-v2-container.yaml")
        del document["deployment"]["approval"]
        with self.assertRaisesRegex(ManifestV2Error, "explicit deployment approval"):
            validate(document)


if __name__ == "__main__":
    unittest.main()
