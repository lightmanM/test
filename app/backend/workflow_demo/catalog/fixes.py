"""Turn the team's original workflows into demo-ready templates.

Each ``fix_*`` function takes the original workflow (parsed JSON) and returns the template
committed under ``catalog/<id>/``. The fixes are the ones agreed for the demo (see
docs/implementation-plan.md, rule R12) plus template conventions:

* credentials point at *slots* (``slot:<name>``) that are filled at deploy time;
* per-deployment values are ``__VALUE:<name>__`` placeholders, declared in ``catalog.yaml``.

The functions are strict: if the original no longer has the shape they expect they raise,
so upstream edits by the team can't silently produce a broken template.
"""

from __future__ import annotations

import copy
from typing import Any

from workflow_demo.n8n import workflow_json as wj

Workflow = dict[str, Any]


def value(name: str) -> str:
    """Placeholder for a per-deployment value, replaced by the deploy transform."""
    return f"__VALUE:{name}__"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise wj.WorkflowEditError(message)


def _set_assignment(set_node: wj.Node, name: str, new_value: Any) -> None:
    for assignment in set_node["parameters"]["assignments"]["assignments"]:
        if assignment["name"] == name:
            assignment["value"] = new_value
            return
    raise wj.WorkflowEditError(f"{set_node['name']!r} has no assignment {name!r}")


def _remove_assignment(set_node: wj.Node, name: str) -> None:
    assignments = set_node["parameters"]["assignments"]["assignments"]
    kept = [a for a in assignments if a["name"] != name]
    _require(len(kept) == len(assignments) - 1, f"{set_node['name']!r} has no assignment {name!r}")
    set_node["parameters"]["assignments"]["assignments"] = kept


def _replace_once(text: str, old: str, new: str, where: str) -> str:
    count = text.count(old)
    _require(count == 1, f"expected exactly one {old!r} in {where}, found {count}")
    return text.replace(old, new)


def _renumber_node_ids(wf: Workflow) -> None:
    for n in wf["nodes"]:
        n["id"] = wj.new_node_id(wf["name"], n["name"])


def _sheet_column(column_id: str) -> dict[str, Any]:
    return {
        "id": column_id,
        "displayName": column_id,
        "required": False,
        "defaultMatch": False,
        "display": True,
        "type": "string",
        "canBeUsedToMatch": True,
        "removed": False,
    }


# --------------------------------------------------------------------------- uptime monitor

UPTIME_SITES_TAB = "Sites"
UPTIME_LOG_TAB = "Log"
UPTIME_SCHEDULE_MINUTES = 30


def fix_uptime(original: Workflow) -> Workflow:
    """n8n template 2327 "Host your own uptime monitoring with scheduled triggers"."""
    wf = wj.as_template(original, "Uptime monitor (demo)")

    # The Gmail alert node isn't connected to anything; drop it (and the Gmail scope it would need).
    wj.remove_node(wf, "Send Email Alert1")

    wj.node(wf, "Schedule Trigger")["parameters"] = {
        "rule": {"interval": [{"field": "minutes", "minutesInterval": UPTIME_SCHEDULE_MINUTES}]}
    }

    # The site check sent one empty header entry; it serves no purpose and can fail validation.
    site_test = wj.node(wf, "Perform Site Test")["parameters"]
    site_test.pop("sendHeaders", None)
    site_test.pop("headerParameters", None)

    # All sheet nodes use the spreadsheet created for the user at deploy time, addressed by tab name.
    for name, tab in (
        ("Get Sites", UPTIME_SITES_TAB),
        ("Log Uptime Event", UPTIME_LOG_TAB),
        ("Update Site Status", UPTIME_SITES_TAB),
    ):
        sheet_node = wj.node(wf, name)
        sheet_node["parameters"]["documentId"] = {
            "__rl": True,
            "mode": "id",
            "value": value("spreadsheet_id"),
        }
        sheet_node["parameters"]["sheetName"] = {"__rl": True, "mode": "name", "value": tab}
        wj.set_credential_slot(sheet_node, "googleSheetsOAuth2Api", "google")

    # Original wrote a placeholder column to a third tab, so a site's status never changed and a
    # down site alerted on every run. Write the new status back to the site's row instead.
    update = wj.node(wf, "Update Site Status")
    _require(
        update["parameters"].get("operation") == "appendOrUpdate", "Update Site Status operation changed"
    )
    status = "$('Calculate Status').item.json"
    update["parameters"]["columns"] = {
        "mappingMode": "defineBelow",
        "value": {
            "Property": f"={{{{ {status}.Property }}}}",
            "Status": f"={{{{ ({status}.DOWN_FROM_UP || {status}.DOWN_FROM_DOWN) ? 'DOWN' : 'UP' }}}}",
        },
        "matchingColumns": ["Property"],
        "schema": [_sheet_column("Property"), _sheet_column("Status")],
        "attemptToConvertTypes": False,
        "convertFieldsToString": False,
    }

    slack = wj.node(wf, "Send Chat Alert")
    slack["parameters"]["authentication"] = "accessToken"
    slack["parameters"]["channelId"] = {"__rl": True, "mode": "id", "value": value("slack_channel")}
    wj.set_credential_slot(slack, "slackApi", "slack")

    _require(not wj.real_credential_refs(wf), "uptime template still references original credentials")
    return wf


# ----------------------------------------------------------------------- meegle daily digest

MEEGLE_MCP_NODES = ("MCP: fetch bugs (issue)", "MCP: fetch stories")


def fix_meegle_digest(compiled: Workflow) -> Workflow:
    """Meegle daily digest, compiled from the team's n8n Workflow-SDK code."""
    wf = wj.as_template(compiled, "Meegle daily digest (demo)")
    wf["settings"] = {"executionOrder": "v1", **(compiled.get("settings") or {})}

    config = wj.node(wf, "Config")
    # The token must never live in node parameters: it moves to an n8n Header Auth credential.
    _remove_assignment(config, "meegle_mcp_token")
    _set_assignment(config, "delivery_mode", "slack")
    _set_assignment(config, "slack_webhook_url", value("slack_webhook_url"))
    _set_assignment(config, "window_hours", value("window_hours"))
    _set_assignment(config, "meegle_project_key", value("meegle_project_key"))
    _set_assignment(config, "meegle_simple_name", value("meegle_simple_name"))

    for name in MEEGLE_MCP_NODES:
        http = wj.node(wf, name)
        headers = http["parameters"]["headerParameters"]["parameters"]
        kept = [h for h in headers if h.get("name") != "X-Mcp-Token"]
        _require(len(kept) == len(headers) - 1, f"{name!r} has no X-Mcp-Token header")
        http["parameters"]["headerParameters"]["parameters"] = kept
        http["parameters"]["authentication"] = "genericCredentialType"
        http["parameters"]["genericAuthType"] = "httpHeaderAuth"
        wj.set_credential_slot(http, "httpHeaderAuth", "meegle_mcp")

    # Only post to Slack when a webhook URL is configured.
    compose = wj.node(wf, "Compose digest")
    has_webhook = {
        "name": "Has Slack webhook",
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": wj.position_near(compose, dx=100, dy=-150),
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                "conditions": [
                    {
                        "id": "has-slack-webhook",
                        "leftValue": "={{ $json.slack_webhook_url }}",
                        "rightValue": "",
                        "operator": {"type": "string", "operation": "notEmpty", "singleValue": True},
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
    }
    wj.insert_between(wf, "Compose digest", "POST to Slack webhook", has_webhook)

    _renumber_node_ids(wf)
    return wf


# ---------------------------------------------------------------------------- medium digest

MEDIUM_MAX_ARTICLES = 5
MEDIUM_READER_TIMEOUT_MS = 45_000
MEDIUM_READER_NODE_TIMEOUT_MS = 60_000
MEDIUM_LLM_TIMEOUT_MS = 60_000


def fix_medium_digest(original: Workflow) -> Workflow:
    """Medium digest: Gmail -> article links -> reader service -> LLM -> Slack."""
    wf = wj.as_template(original, "Medium digest (demo)")

    config = wj.node(wf, "Workflow configuration")
    _set_assignment(config, "freediumEndpoint", value("reader_url"))
    _set_assignment(config, "llmEndpoint", value("llm_endpoint"))
    _set_assignment(config, "llmModel", value("llm_model"))
    _set_assignment(config, "slackChannel", value("slack_channel"))

    # Cap the run so it fits n8n Cloud's execution time limit.
    extract = wj.node(wf, "Extract article links")
    extract["parameters"]["jsCode"] = _replace_once(
        extract["parameters"]["jsCode"],
        ".slice(0, 100)",
        f".slice(0, {MEDIUM_MAX_ARTICLES})",
        "Extract article links",
    )

    reader = wj.node(wf, "Fetch article through Freedium")
    reader["parameters"]["jsonBody"] = _replace_once(
        reader["parameters"]["jsonBody"],
        "timeoutMs: 60000",
        f"timeoutMs: {MEDIUM_READER_TIMEOUT_MS}",
        "Fetch article through Freedium",
    )
    reader["parameters"]["options"]["timeout"] = MEDIUM_READER_NODE_TIMEOUT_MS
    reader["parameters"]["authentication"] = "genericCredentialType"
    reader["parameters"]["genericAuthType"] = "httpHeaderAuth"
    wj.set_credential_slot(reader, "httpHeaderAuth", "reader")

    llm = wj.node(wf, "Classify and summarize article")
    _require(llm["parameters"].get("nodeCredentialType") == "openAiApi", "LLM node credential type changed")
    llm["parameters"]["options"]["timeout"] = MEDIUM_LLM_TIMEOUT_MS
    wj.set_credential_slot(llm, "openAiApi", "openai")

    wj.set_credential_slot(wj.node(wf, "Find Medium Daily Digest emails"), "gmailOAuth2", "google")
    slack = wj.node(wf, "Send report to Slack")
    _require(slack["parameters"].get("authentication") == "accessToken", "Slack node auth changed")
    wj.set_credential_slot(slack, "slackApi", "slack")

    _require(not wj.real_credential_refs(wf), "medium template still references original credentials")
    return wf


# ------------------------------------------------------------------------ github merge (Make)


def fix_github_merge_blueprint(original: Workflow) -> Workflow:
    """Make blueprint "GitHub 合并提交 Diff 通知前端", prepared for a Make Bridge template.

    Adds a merged-only filter in front of the commit lookup (unmerged PR updates have no
    merge commit and made the scenario error) and removes the owner's connection IDs.
    Repo and channel stay as sample values; they become end-user inputs in the Bridge
    template (see catalog/github-merge-slack/make-setup.md).
    """
    bp = copy.deepcopy(original)
    bp["name"] = "GitHub merge → Slack (demo template)"
    modules = {m["id"]: m for m in bp["flow"]}
    _require(modules.get(1, {}).get("module") == "github:newPullRequest", "module 1 is not the PR trigger")
    _require(modules.get(2, {}).get("module") == "github:makeRestApiCall", "module 2 is not the API call")
    modules[2]["filter"] = {
        "name": "Merged pull requests only",
        "conditions": [[{"a": "{{1.merged}}", "b": "true", "o": "boolean:equal"}]],
    }
    for module in bp["flow"]:
        if "__IMTCONN__" in module.get("parameters", {}):
            module["parameters"]["__IMTCONN__"] = None
    return bp
