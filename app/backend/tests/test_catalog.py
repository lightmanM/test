import shutil

import pytest
import yaml

from workflow_demo import paths
from workflow_demo.catalog.loader import CatalogError, load_catalog, load_template, template_values
from workflow_demo.catalog.models import ConnectorKind, Platform


def test_catalog_loads_in_display_order():
    catalog = load_catalog()
    assert [w.id for w in catalog.workflows] == [
        "uptime-monitor",
        "meegle-daily-digest",
        "medium-digest",
        "github-merge-slack",
        "slack-meegle-bot",
    ]
    assert {w.platform for w in catalog.workflows} == {Platform.N8N, Platform.MAKE, Platform.MODAL}
    assert catalog.connectors["meegle_mcp_token"].kind is ConnectorKind.MANUAL
    assert catalog.connectors["meegle_mcp_token"].secret


def test_n8n_templates_declare_every_value():
    catalog = load_catalog()
    for entry in catalog.workflows:
        if entry.n8n:
            assert template_values(load_template(entry)) == set(entry.n8n.values)


@pytest.fixture
def catalog_copy(tmp_path):
    target = tmp_path / "catalog"
    shutil.copytree(paths.CATALOG_DIR, target)
    return target


def edit_yaml(path, change):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_undeclared_template_value_is_rejected(catalog_copy):
    edit_yaml(
        catalog_copy / "uptime-monitor" / "catalog.yaml", lambda d: d["n8n"]["values"].pop("slack_channel")
    )
    with pytest.raises(CatalogError, match="template values"):
        load_catalog(catalog_copy)


def test_credential_slot_type_mismatch_is_rejected(catalog_copy):
    def change(d):
        d["n8n"]["credentials"]["slack"]["type"] = "slackOAuth2Api"

    edit_yaml(catalog_copy / "uptime-monitor" / "catalog.yaml", change)
    with pytest.raises(CatalogError, match="credential slots"):
        load_catalog(catalog_copy)


def test_unknown_connector_is_rejected(catalog_copy):
    edit_yaml(
        catalog_copy / "medium-digest" / "catalog.yaml",
        lambda d: d["connectors"].append({"id": "dropbox", "purpose": "x"}),
    )
    with pytest.raises(CatalogError, match="unknown connector"):
        load_catalog(catalog_copy)


def test_make_workflow_requires_platform_popup_connectors(catalog_copy):
    edit_yaml(
        catalog_copy / "github-merge-slack" / "catalog.yaml",
        lambda d: d["connectors"].append({"id": "slack", "purpose": "x"}),
    )
    with pytest.raises(CatalogError, match="Make's popup"):
        load_catalog(catalog_copy)


def test_platform_section_must_match(catalog_copy):
    edit_yaml(catalog_copy / "slack-meegle-bot" / "catalog.yaml", lambda d: d.pop("modal"))
    with pytest.raises(CatalogError, match="section is missing"):
        load_catalog(catalog_copy)
