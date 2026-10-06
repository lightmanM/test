"""Golden checks on the deploy transform for every n8n template in the catalog."""

import json

import pytest

from workflow_demo.catalog.loader import load_catalog, load_template
from workflow_demo.catalog.models import Platform
from workflow_demo.n8n import workflow_json as wj
from workflow_demo.n8n.transform import (
    NODE_KEYS,
    RUN_NODE_NAME,
    SETTINGS_KEYS,
    TRIGGER_TYPES,
    CredentialRef,
    RunHook,
    TransformError,
    build_workflow,
)

CATALOG = load_catalog()
N8N_ENTRIES = [e for e in CATALOG.workflows if e.platform is Platform.N8N]
SAMPLE = {
    "slack_channel": "C0123ABCD",
    "spreadsheet_id": "sheet-123",
    "google_api": "http://demo.internal:8000/api/google-relay",
    "meegle_project_key": "proj",
    "meegle_simple_name": "space",
    "window_hours": 720,
    "reader_url": "https://reader.example/extract",
    "llm_endpoint": "https://api.openai.com/v1/chat/completions",
    "llm_model": "gpt-4o-mini",
}
HOOK = RunHook(path="0b5f0d8e-hook", credential=CredentialRef("cred-run", "run now"))


def build(entry, **overrides):
    values = {name: SAMPLE[name] for name in entry.n8n.values}
    credentials = {slot: CredentialRef(f"cred-{slot}", f"demo {slot}") for slot in entry.n8n.credentials}
    kwargs = {"name": f"[demo] {entry.name}", "values": values, "credentials": credentials, "run_hook": HOOK}
    kwargs.update(overrides)
    return build_workflow(load_template(entry), **kwargs)


def test_catalog_has_three_n8n_workflows():
    assert [e.id for e in N8N_ENTRIES] == ["uptime-monitor", "meegle-daily-digest", "medium-digest"]


@pytest.mark.parametrize("entry", N8N_ENTRIES, ids=lambda e: e.id)
def test_template_becomes_a_deployable_workflow(entry):
    template = load_template(entry)
    wf = build(entry)
    text = json.dumps(wf, ensure_ascii=False)

    assert set(wf) == {"name", "nodes", "connections", "settings"}
    assert "__VALUE:" not in text and "slot:" not in text
    assert set(wf["settings"]) <= SETTINGS_KEYS and wf["settings"]["saveDataSuccessExecution"] == "all"
    for node in wf["nodes"]:
        assert set(node) <= NODE_KEYS, node["name"]
        assert node["id"]

    # Every credential slot now points at the credential made for this deployment.
    for _, credential_type, slot in wj.credential_slots(template):
        assert f'"cred-{slot}"' in text, (credential_type, slot)

    # Run now: a header-auth webhook wired to wherever the template's triggers start.
    run = wj.node(wf, RUN_NODE_NAME)
    assert run["type"] == "n8n-nodes-base.webhook"
    assert run["parameters"]["authentication"] == "headerAuth"
    assert run["parameters"]["path"] == run["webhookId"] == HOOK.path
    assert run["credentials"] == {"httpHeaderAuth": {"id": "cred-run", "name": "run now"}}
    trigger_targets = {
        t for n in template["nodes"] if n["type"] in TRIGGER_TYPES for t in wj.targets(template, n["name"])
    }
    assert trigger_targets and set(wj.targets(wf, RUN_NODE_NAME)) == trigger_targets

    # The template itself is untouched.
    assert "__VALUE:" in json.dumps(load_template(entry))


def test_values_keep_their_type():
    entry = CATALOG.workflow("meegle-daily-digest")
    config = wj.node(build(entry), "Config")
    by_name = {a["name"]: a["value"] for a in config["parameters"]["assignments"]["assignments"]}
    assert by_name["window_hours"] == 720
    assert by_name["slack_channel"] == "C0123ABCD"


def test_uptime_sheet_and_channel_are_filled_in():
    wf = build(CATALOG.workflow("uptime-monitor"))
    config = wj.node(wf, "Spreadsheet")["parameters"]["assignments"]["assignments"]
    assert {a["name"]: a["value"] for a in config} == {
        "googleApi": "http://demo.internal:8000/api/google-relay",
        "spreadsheetId": "sheet-123",
    }
    assert wj.node(wf, "Send Chat Alert")["parameters"]["channelId"]["value"] == "C0123ABCD"


def test_without_run_hook_no_webhook_is_added():
    wf = build(CATALOG.workflow("uptime-monitor"), run_hook=None)
    assert not wj.has_node(wf, RUN_NODE_NAME)


def test_errors():
    entry = CATALOG.workflow("meegle-daily-digest")
    values = {name: SAMPLE[name] for name in entry.n8n.values}
    with pytest.raises(TransformError, match="no value"):
        build(entry, values={k: v for k, v in values.items() if k != "window_hours"})
    with pytest.raises(TransformError, match="can't start with '='"):
        build(entry, values={**values, "meegle_project_key": "={{ $env.N8N_SECRET }}"})
    with pytest.raises(TransformError, match="no credential"):
        build(entry, credentials={})

    template = load_template(entry)
    wj.node(template, "Config")["parameters"]["assignments"]["assignments"][0]["value"] = (
        "x __VALUE:slack_channel__"
    )
    with pytest.raises(TransformError, match="whole parameter"):
        build_workflow(template, name="x", values=values, credentials={}, run_hook=None)
