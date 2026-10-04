import pytest

from workflow_demo.n8n import workflow_json as wj


def make_wf():
    return {
        "name": "t",
        "nodes": [
            {"name": "A", "type": "x", "position": [0, 0], "parameters": {}},
            {"name": "B", "type": "x", "position": [200, 0], "parameters": {}},
            {
                "name": "C",
                "type": "x",
                "position": [400, 0],
                "parameters": {},
                "credentials": {"slackApi": {"id": "123", "name": "Slack"}},
            },
        ],
        "connections": {
            "A": {"main": [[{"node": "B", "type": "main", "index": 0}]]},
            "B": {"main": [[{"node": "C", "type": "main", "index": 0}]]},
        },
        "pinData": {"A": []},
        "active": True,
    }


def test_remove_node_drops_edges_in_both_directions():
    wf = make_wf()
    wj.remove_node(wf, "B")
    assert not wj.has_node(wf, "B")
    assert "B" not in wf["connections"]
    assert wj.targets(wf, "A") == []


def test_insert_between_rewires_edge():
    wf = make_wf()
    wj.insert_between(wf, "A", "B", {"name": "N", "type": "if", "parameters": {}})
    assert wj.targets(wf, "A") == ["N"]
    assert wj.targets(wf, "N") == ["B"]


def test_disconnect_missing_edge_raises():
    with pytest.raises(wj.WorkflowEditError):
        wj.disconnect(make_wf(), "A", "C")


def test_connect_is_idempotent_and_supports_outputs():
    wf = make_wf()
    wj.connect(wf, "A", "C", output=1)
    wj.connect(wf, "A", "C", output=1)
    assert wj.targets(wf, "A", output=1) == ["C"]


def test_credential_slots_and_real_refs():
    wf = make_wf()
    assert wj.real_credential_refs(wf) == [("C", "slackApi", "123")]
    wj.set_credential_slot(wj.node(wf, "C"), "slackApi", "slack")
    assert wj.credential_slots(wf) == [("C", "slackApi", "slack")]
    assert wj.real_credential_refs(wf) == []


def test_as_template_keeps_only_api_fields():
    tpl = wj.as_template(make_wf(), "New name")
    assert set(tpl) == {"name", "nodes", "connections", "settings"}
    assert tpl["name"] == "New name"
    assert tpl["settings"] == {"executionOrder": "v1"}


def test_new_node_id_is_deterministic():
    assert wj.new_node_id("wf", "node") == wj.new_node_id("wf", "node")
    assert wj.new_node_id("wf", "node") != wj.new_node_id("wf", "other")
