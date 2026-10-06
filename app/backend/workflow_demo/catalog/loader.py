"""Load and validate the workflow catalog."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from workflow_demo import paths
from workflow_demo.catalog.models import (
    Catalog,
    Connector,
    ConnectorKind,
    CredentialSource,
    Platform,
    ValueSource,
    WorkflowEntry,
)
from workflow_demo.n8n import workflow_json as wj

VALUE_PATTERN = re.compile(r"__VALUE:([a-z0-9_]+)__")
WORKFLOW_ORDER = (
    "uptime-monitor",
    "meegle-daily-digest",
    "medium-digest",
    "github-merge-slack",
    "slack-meegle-bot",
)


class CatalogError(ValueError):
    pass


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_catalog(catalog_dir: Path | None = None) -> Catalog:
    catalog_dir = catalog_dir or paths.CATALOG_DIR
    if not (catalog_dir / "connectors.yaml").exists():
        raise CatalogError(f"no catalog at {catalog_dir} (set WORKFLOW_DEMO_CATALOG_DIR)")
    connectors = {
        key: Connector(id=key, **raw) for key, raw in _read_yaml(catalog_dir / "connectors.yaml").items()
    }
    entries = []
    for entry_dir in sorted(p for p in catalog_dir.iterdir() if (p / "catalog.yaml").exists()):
        raw = _read_yaml(entry_dir / "catalog.yaml")
        if raw.get("id") != entry_dir.name:
            raise CatalogError(f"{entry_dir.name}/catalog.yaml: id must match the folder name")
        entries.append(WorkflowEntry(**raw))
    order = {wid: i for i, wid in enumerate(WORKFLOW_ORDER)}
    entries.sort(key=lambda e: (order.get(e.id, len(order)), e.id))
    catalog = Catalog(connectors=connectors, workflows=entries)
    for entry in catalog.workflows:
        validate_entry(catalog, entry, catalog_dir / entry.id)
    return catalog


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return load_catalog()


def load_template(entry: WorkflowEntry, catalog_dir: Path | None = None) -> dict[str, Any]:
    catalog_dir = catalog_dir or paths.CATALOG_DIR
    if entry.n8n is None:
        raise CatalogError(f"{entry.id} has no n8n template")
    with (catalog_dir / entry.id / entry.n8n.template).open(encoding="utf-8") as fh:
        return json.load(fh)


def template_values(template: dict[str, Any]) -> set[str]:
    return set(VALUE_PATTERN.findall(json.dumps(template, ensure_ascii=False)))


def validate_entry(catalog: Catalog, entry: WorkflowEntry, entry_dir: Path) -> None:
    def fail(message: str) -> None:
        raise CatalogError(f"{entry.id}: {message}")

    for connector in entry.connectors:
        if connector.id not in catalog.connectors:
            fail(f"unknown connector {connector.id!r}")
    setting_keys = {s.key for s in entry.settings}
    if len(setting_keys) != len(entry.settings):
        fail("duplicate setting keys")

    specs = {Platform.N8N: entry.n8n, Platform.MAKE: entry.make, Platform.MODAL: entry.modal}
    if specs[entry.platform] is None:
        fail(f"platform is {entry.platform.value} but the {entry.platform.value} section is missing")
    for platform, spec in specs.items():
        if platform != entry.platform and spec is not None:
            fail(f"has a {platform.value} section but platform is {entry.platform.value}")

    connector_ids = {c.id for c in entry.connectors}
    if entry.platform is Platform.MAKE:
        for connector in entry.connectors:
            if catalog.connectors[connector.id].kind is not ConnectorKind.PLATFORM_POPUP:
                fail("Make workflows connect accounts in Make's popup only")
        if not (entry_dir / entry.make.blueprint).exists():
            fail(f"missing {entry.make.blueprint}")
        if not (entry_dir / entry.make.setup_doc).exists():
            fail(f"missing {entry.make.setup_doc}")

    if entry.platform is Platform.N8N:
        spec = entry.n8n
        template_path = entry_dir / spec.template
        if not template_path.exists():
            fail(f"missing {spec.template}")
        template = load_template(entry, entry_dir.parent)

        used_values = template_values(template)
        declared_values = set(spec.values)
        if used_values != declared_values:
            fail(f"template values {sorted(used_values)} != declared {sorted(declared_values)}")
        for name, source in spec.values.items():
            if source is ValueSource.SETTING and name not in setting_keys:
                fail(f"value {name!r} comes from a setting that isn't declared")

        used_slots = {(slot, cred_type) for _, cred_type, slot in wj.credential_slots(template)}
        declared_slots = {(slot, s.type) for slot, s in spec.credentials.items()}
        if used_slots != declared_slots:
            fail(f"template credential slots {sorted(used_slots)} != declared {sorted(declared_slots)}")
        for slot, credential in spec.credentials.items():
            if (
                credential.source in (CredentialSource.CONNECTION, CredentialSource.GOOGLE_RELAY)
                and credential.ref not in connector_ids
            ):
                fail(f"credential slot {slot!r} uses connector {credential.ref!r} not listed in connectors")
            if credential.source is CredentialSource.GOOGLE_RELAY:
                if credential.type != "httpHeaderAuth":
                    fail(f"credential slot {slot!r}: the Google relay key is an httpHeaderAuth credential")
                if not spec.google_apis:
                    fail(f"credential slot {slot!r} uses the Google relay but google_apis is empty")
        if spec.google_apis and not any(
            c.source is CredentialSource.GOOGLE_RELAY for c in spec.credentials.values()
        ):
            fail("google_apis is set but no credential slot uses the Google relay")
        leftovers = wj.real_credential_refs(template)
        if leftovers:
            fail(f"template references real credentials: {leftovers}")
        for result_node in spec.result_nodes:
            if not wj.has_node(template, result_node):
                fail(f"result node {result_node!r} not in template")
