"""Contract acceptance for vendored uda.yaml JSON Schema v1."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/uda-manifest-v1.schema.json").read_text())
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA)


def example():
    return {
        "schema_version": 1,
        "application": {"name": "demo-app", "display_name": "Demo App",
                        "description": "Managed web app", "group": "Development"},
        "source": {"branch": "main"},
        "runtime": {"type": "python", "version": "3.12", "working_dir": "app"},
        "build": {"working_dir": "app", "commands": [["python", "-m", "compileall", "."]]},
        "service": {"type": "systemd", "entrypoint": ["python", "main.py"],
                    "port": "auto", "health_path": "/health"},
        "proxy": {"enabled": True, "path": "/apps/demo-app/", "authentication": "uda"},
        "environment": {"required": ["SECRET_KEY"]},
        "deployment": {"auto_update": False, "rollback": True,
                       "github_reporting": False},
    }


def test_complete_v1_example_valid():
    VALIDATOR.validate(example())


def test_static_site_contract_valid():
    item = example()
    item["runtime"] = {"type": "static", "working_dir": "dist"}
    item["service"] = {"type": "static"}
    VALIDATOR.validate(item)


def test_node_contract_valid():
    item = example()
    item["runtime"] = {"type": "node", "version": "22"}
    item["service"]["entrypoint"] = ["node", "server.js"]
    VALIDATOR.validate(item)


@pytest.mark.parametrize("section,key,value", [
    ("application", "privileged", True),
    ("runtime", "run_as", "root"),
    ("build", "script", "curl https://example.invalid"),
    ("service", "allow_root", True),
    ("proxy", "caddy_directives", "reverse_proxy evil"),
    ("environment", "SECRET_KEY", "password"),
    ("deployment", "force", True),
])
def test_nested_unknown_fields_rejected(section, key, value):
    item = example()
    item[section][key] = value
    assert list(VALIDATOR.iter_errors(item))


@pytest.mark.parametrize("value", ["../secrets", "/etc", "src/../../etc", ".hidden"])
def test_traversal_or_absolute_paths_rejected(value):
    item = example()
    item["runtime"]["working_dir"] = value
    assert list(VALIDATOR.iter_errors(item))


def test_unapproved_schema_version_rejected():
    item = example()
    item["schema_version"] = 2
    assert list(VALIDATOR.iter_errors(item))
