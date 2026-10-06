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


def _assignment(set_node: wj.Node, name: str) -> dict[str, Any]:
    for assignment in set_node["parameters"]["assignments"]["assignments"]:
        if assignment["name"] == name:
            return assignment
    raise wj.WorkflowEditError(f"{set_node['name']!r} has no assignment {name!r}")


def _set_assignment(set_node: wj.Node, name: str, new_value: Any) -> None:
    _assignment(set_node, name)["value"] = new_value


def _rename_assignment(set_node: wj.Node, old: str, new: str, new_value: Any) -> None:
    assignment = _assignment(set_node, old)
    assignment["name"] = new
    assignment["value"] = new_value


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


def _replace_node(wf: Workflow, name: str, new: wj.Node) -> wj.Node:
    """Swap a node for a different one under the same name, so its connections and the
    expressions that refer to it keep working."""
    old = wj.node(wf, name)
    node_id = old.get("id") or wj.new_node_id(wf["name"], name)
    old.clear()
    old.update({"id": node_id, "name": name, **new})
    return old


def _relay_call(
    method: str, url: str, *, query: dict[str, str] | None = None, body: str | None = None
) -> wj.Node:
    """An HTTP Request node calling the demo's Google relay (Google through Nango's proxy) with the
    deployment's relay key (``google`` slot, an httpHeaderAuth credential)."""
    parameters: dict[str, Any] = {
        "method": method,
        "url": url,
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
    }
    if query:
        parameters["sendQuery"] = True
        parameters["queryParameters"] = {"parameters": [{"name": k, "value": v} for k, v in query.items()]}
    if body is not None:
        parameters |= {"sendBody": True, "specifyBody": "json", "jsonBody": body}
    parameters["options"] = {}
    n: wj.Node = {"type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "parameters": parameters}
    wj.set_credential_slot(n, "httpHeaderAuth", "google")
    return n


def _code(js: str) -> wj.Node:
    return {
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "parameters": {"mode": "runOnceForAllItems", "jsCode": js},
    }


# --------------------------------------------------------------------------- uptime monitor

UPTIME_SITES_TAB = "Sites"
UPTIME_LOG_TAB = "Log"
UPTIME_SCHEDULE_MINUTES = 30
UPTIME_SITE_TIMEOUT_MS = 15_000  # a site that answers slower counts as DOWN
UPTIME_CONFIG_NODE = "Spreadsheet"
_UPTIME_CONFIG = f"$('{UPTIME_CONFIG_NODE}').first().json"
UPTIME_SHEET_URL = (
    f"{{{{ {_UPTIME_CONFIG}.googleApi }}}}/sheets/v4/spreadsheets/{{{{ {_UPTIME_CONFIG}.spreadsheetId }}}}"
)
UPTIME_LOG_COLUMNS = ("date", "Property", "UP_FROM_UP", "DOWN_FROM_DOWN", "UP_FROM_DOWN", "DOWN_FROM_UP")
UPTIME_SITES_JS = """\
// One item per site in the Sites tab (row 2 onwards), like the Google Sheets node made.
const rows = $input.first().json.values || [];
return rows
  .map((row, index) => ({
    Property: String(row[0] ?? '').trim(),
    Status: String(row[1] ?? '').trim(),
    row_number: index + 2,
  }))
  .filter((site) => site.Property)
  .map((site) => ({ json: site }));
"""


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

    # The loop handed every site to the HTTP check and to a cross-join Merge at once, so with two
    # or more sites each response was paired with each site (false alerts, conflicting status
    # writes). Process one site per iteration.
    loop = wj.node(wf, "For Each Site...")
    _require(loop["type"] == "n8n-nodes-base.splitInBatches", "For Each Site... is not a loop node")
    loop["parameters"]["batchSize"] = 1

    # A site that doesn't answer (timeout, DNS failure, refused) made the check throw and failed the
    # whole run: neverError only covers HTTP error codes. Continue with the failed item (it has no
    # statusCode) and give up after UPTIME_SITE_TIMEOUT_MS so one dead site doesn't stall the run.
    check = wj.node(wf, "Perform Site Test")
    _require(check["type"] == "n8n-nodes-base.httpRequest", "Perform Site Test is not an HTTP node")
    check["onError"] = "continueRegularOutput"
    check["parameters"].setdefault("options", {})["timeout"] = UPTIME_SITE_TIMEOUT_MS

    # Reachable means an HTTP status below 400; no status at all (the failed request above) is DOWN.
    # A blank Status cell (e.g. a newly added site) counts as UP; the original matched no route.
    calc = wj.node(wf, "Calculate Status")
    reachable = "($json.statusCode > 0 && $json.statusCode < 400)"
    for name, condition in (
        ("UP_FROM_UP", f"{reachable} && $json.Status !== 'DOWN'"),
        ("DOWN_FROM_DOWN", f"!{reachable} && $json.Status === 'DOWN'"),
        ("UP_FROM_DOWN", f"{reachable} && $json.Status === 'DOWN'"),
        ("DOWN_FROM_UP", f"!{reachable} && $json.Status !== 'DOWN'"),
    ):
        _set_assignment(calc, name, f"={{{{ {condition} }}}}")
    # A failed request has no Date header: use the run's own time (same HTTP-date format).
    _set_assignment(calc, "date", "={{ $json.headers?.date ?? $now.toUTC().toHTTP() }}")

    # Google Sheets goes through the demo's Google relay (Nango's proxy holds the user's tokens; n8n
    # gets no Google credential), so the three Sheets nodes become HTTP calls to the Sheets API on
    # the spreadsheet created for the user at deploy time.
    for name in ("Get Sites", "Log Uptime Event", "Update Site Status"):
        _require(wj.node(wf, name)["type"] == "n8n-nodes-base.googleSheets", f"{name} is not a Sheets node")
    _require(wj.targets(wf, "Schedule Trigger") == ["Get Sites"], "uptime start changed")
    get_sites = wj.node(wf, "Get Sites")
    wj.insert_between(
        wf,
        "Schedule Trigger",
        "Get Sites",
        {
            "id": wj.new_node_id(wf["name"], UPTIME_CONFIG_NODE),
            "name": UPTIME_CONFIG_NODE,
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": wj.position_near(wj.node(wf, "Schedule Trigger"), dx=128),
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": "google-api",
                            "name": "googleApi",
                            "type": "string",
                            "value": value("google_api"),
                        },
                        {
                            "id": "spreadsheet-id",
                            "name": "spreadsheetId",
                            "type": "string",
                            "value": value("spreadsheet_id"),
                        },
                    ]
                },
                "options": {},
            },
        },
    )
    wj.insert_between(
        wf,
        UPTIME_CONFIG_NODE,
        "Get Sites",
        {
            "id": wj.new_node_id(wf["name"], "Read Sites"),
            "name": "Read Sites",
            "position": list(get_sites["position"]),
            **_relay_call("GET", f"={UPTIME_SHEET_URL}/values/{UPTIME_SITES_TAB}!A2:B"),
        },
    )
    # The Sheets node made one item per row (with its row number); so does this.
    _replace_node(
        wf, "Get Sites", {"position": wj.position_near(get_sites, dx=152), **_code(UPTIME_SITES_JS)}
    )

    # Status Router -> Calculate Status items: one row per check in the Log tab.
    log_row = ", ".join(f"$json.{column}" for column in UPTIME_LOG_COLUMNS)
    log = wj.node(wf, "Log Uptime Event")
    _replace_node(
        wf,
        "Log Uptime Event",
        {
            "position": log["position"],
            **_relay_call(
                "POST",
                f"={UPTIME_SHEET_URL}/values/{UPTIME_LOG_TAB}!A:F:append",
                query={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                body=f"={{{{ JSON.stringify({{ values: [[{log_row}]] }}) }}}}",
            ),
        },
    )

    # Original wrote a placeholder column to a third tab, so a site's status never changed and a
    # down site alerted on every run. Write the new status into the site's own row instead.
    status = "$('Calculate Status').item.json"
    calc["parameters"]["assignments"]["assignments"].append(
        {"id": "row-number", "name": "row_number", "type": "number", "value": "={{ $json.row_number }}"}
    )
    update = wj.node(wf, "Update Site Status")
    _require(
        update["parameters"].get("operation") == "appendOrUpdate", "Update Site Status operation changed"
    )
    new_status = f"({status}.DOWN_FROM_UP || {status}.DOWN_FROM_DOWN) ? 'DOWN' : 'UP'"
    _replace_node(
        wf,
        "Update Site Status",
        {
            "position": update["position"],
            **_relay_call(
                "PUT",
                f"={UPTIME_SHEET_URL}/values/{UPTIME_SITES_TAB}!B{{{{ {status}.row_number }}}}",
                query={"valueInputOption": "RAW"},
                body=f"={{{{ JSON.stringify({{ values: [[{new_status}]] }}) }}}}",
            ),
        },
    )

    slack = wj.node(wf, "Send Chat Alert")
    # Alerts also fire for DOWN_FROM_DOWN and UP_FROM_DOWN; the text only knew DOWN_FROM_UP and
    # called a site that's still down "UP".
    slack["parameters"]["text"] = _replace_once(
        slack["parameters"]["text"],
        """{{ $('Calculate Status').item.json["DOWN_FROM_UP"] ? 'DOWN' : 'UP' }}""",
        f"{{{{ {status}.DOWN_FROM_UP ? 'DOWN' : ({status}.DOWN_FROM_DOWN ? 'still DOWN' : 'back UP') }}}}",
        "Send Chat Alert text",
    )
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
    # The incoming-webhook URL is itself a secret and would sit in node parameters and execution
    # data. Post with the Slack bot token (a credential) to a chosen channel instead.
    _rename_assignment(config, "slack_webhook_url", "slack_channel", value("slack_channel"))
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

    old_post = wj.node(wf, "POST to Slack webhook")
    _require(
        wj.targets(wf, "Compose digest") == ["POST to Slack webhook", "Done (log only)"],
        "digest tail changed",
    )
    wj.remove_node(wf, "POST to Slack webhook")
    post = wj.add_node(
        wf,
        {
            "name": "Post digest to Slack",
            "type": "n8n-nodes-base.slack",
            "typeVersion": 2.3,
            "position": old_post["position"],
            "parameters": {
                "authentication": "accessToken",
                "resource": "message",
                "operation": "post",
                "select": "channel",
                "channelId": {"__rl": True, "mode": "id", "value": value("slack_channel")},
                "text": "={{ $json.text }}",
                "otherOptions": {"mrkdwn": True, "unfurl_links": False, "unfurl_media": False},
            },
        },
    )
    wj.set_credential_slot(post, "slackApi", "slack")

    # Only post when a channel is configured (the original posted even with no destination set).
    compose = wj.node(wf, "Compose digest")
    has_channel = {
        "name": "Has Slack channel",
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": wj.position_near(compose, dx=100, dy=-150),
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                "conditions": [
                    {
                        "id": "has-slack-channel",
                        "leftValue": "={{ $('Config').first().json.slack_channel }}",
                        "rightValue": "",
                        "operator": {"type": "string", "operation": "notEmpty", "singleValue": True},
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
    }
    wj.add_node(wf, has_channel)
    wj.connect(wf, "Compose digest", "Has Slack channel")
    wj.connect(wf, "Has Slack channel", "Post digest to Slack")

    _renumber_node_ids(wf)
    return wf


# ---------------------------------------------------------------------------- medium digest

MEDIUM_MAX_ARTICLES = 5
MEDIUM_READER_TIMEOUT_MS = 45_000
MEDIUM_READER_NODE_TIMEOUT_MS = 60_000
MEDIUM_LLM_TIMEOUT_MS = 60_000
MEDIUM_MAX_MESSAGES = 20  # newest matching emails read per run (the 5 articles come from these)
MEDIUM_GMAIL_NODE = "Find Medium Daily Digest emails"
_MEDIUM_CONFIG = "$('Workflow configuration').first().json"
_MEDIUM_WINDOW = "$('Build rolling 7-day window').first().json"
MEDIUM_MESSAGE_IDS_JS = """\
return ($input.first().json.messages || []).map((message) => ({ json: { id: message.id } }));
"""
# Gmail API messages (format=full), shaped like the Gmail node's output that "Extract article
# links" reads: payload parts, numeric internalDate, date and subject from the headers.
MEDIUM_MESSAGES_JS = """\
return $input.all()
  .map((item) => item.json)
  .filter((message) => message.id && message.payload)
  .map((message) => {
    const headers = {};
    for (const header of message.payload.headers || []) {
      headers[String(header.name).toLowerCase()] = header.value;
    }
    return { json: {
      id: message.id,
      threadId: message.threadId,
      labelIds: message.labelIds || [],
      snippet: message.snippet || '',
      internalDate: Number(message.internalDate) || 0,
      date: headers.date || null,
      subject: headers.subject || '',
      from: headers.from || '',
      payload: message.payload,
    } };
  });
"""
# Articles are processed one after another, so a run takes roughly 5 x (fetch + LLM). Typical runs
# take 1-3 minutes; a worst case (every call hitting its timeout) can exceed n8n Cloud Starter's
# 5-minute limit, which is why the Pro plan (40 minutes) is recommended.


def fix_medium_digest(original: Workflow) -> Workflow:
    """Medium digest: Gmail -> article links -> reader service -> LLM -> Slack."""
    wf = wj.as_template(original, "Medium digest (demo)")

    config = wj.node(wf, "Workflow configuration")
    _set_assignment(config, "freediumEndpoint", value("reader_url"))
    _set_assignment(config, "llmEndpoint", value("llm_endpoint"))
    _set_assignment(config, "llmModel", value("llm_model"))
    _set_assignment(config, "slackChannel", value("slack_channel"))

    # Cap the run length (see MEDIUM_* above).
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

    _medium_gmail_through_relay(wf, config)
    slack = wj.node(wf, "Send report to Slack")
    _require(slack["parameters"].get("authentication") == "accessToken", "Slack node auth changed")
    wj.set_credential_slot(slack, "slackApi", "slack")

    _require(not wj.real_credential_refs(wf), "medium template still references original credentials")
    return wf


def _medium_gmail_through_relay(wf: Workflow, config: wj.Node) -> None:
    """Gmail goes through the demo's Google relay (Nango's proxy holds the user's tokens; n8n gets
    no Google credential): search, then read each message, then shape them like the Gmail node."""
    gmail = wj.node(wf, MEDIUM_GMAIL_NODE)
    _require(gmail["type"] == "n8n-nodes-base.gmail", f"{MEDIUM_GMAIL_NODE} is not a Gmail node")
    _require(gmail["parameters"].get("operation") == "getAll", "Gmail node operation changed")
    _require(wj.targets(wf, "Build rolling 7-day window") == [MEDIUM_GMAIL_NODE], "Gmail input changed")
    config["parameters"]["assignments"]["assignments"].append(
        {"id": "google-api", "name": "googleApi", "type": "string", "value": value("google_api")}
    )
    window = wj.node(wf, "Build rolling 7-day window")
    _require("gmailSearch" in window["parameters"]["jsCode"], "7-day window no longer sets gmailSearch")

    def seconds(field: str) -> str:
        return f"{{{{ Math.floor(new Date({_MEDIUM_WINDOW}.{field}).getTime() / 1000) }}}}"

    messages_url = f"={{{{ {_MEDIUM_CONFIG}.googleApi }}}}/gmail/v1/users/me/messages"
    x, y = gmail["position"]
    for n in wf["nodes"]:  # make room for the four new nodes
        if n is not gmail and n["position"][0] > x:
            n["position"] = [n["position"][0] + 800, n["position"][1]]
    wj.disconnect(wf, "Build rolling 7-day window", MEDIUM_GMAIL_NODE)
    added = [
        {
            "name": "Search Gmail",
            "position": [x, y],
            **_relay_call(
                "GET",
                messages_url,
                query={
                    # The Gmail node's q + receivedAfter/receivedBefore filters.
                    "q": f"={{{{ {_MEDIUM_WINDOW}.gmailSearch }}}} after:{seconds('receivedAfter')}"
                    f" before:{seconds('receivedBefore')}",
                    "maxResults": str(MEDIUM_MAX_MESSAGES),
                },
            ),
        },
        {
            "name": "Found Gmail messages",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.2,
            "position": [x + 200, y],
            "parameters": {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 2,
                    },
                    "conditions": [
                        {
                            "id": "found-messages",
                            "leftValue": "={{ ($json.messages || []).length }}",
                            "rightValue": 0,
                            "operator": {"type": "number", "operation": "gt"},
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
        },
        {"name": "Gmail message IDs", "position": [x + 400, y - 100], **_code(MEDIUM_MESSAGE_IDS_JS)},
        {
            "name": "Read Gmail message",
            "position": [x + 600, y - 100],
            # A message deleted since the search is skipped (it has no payload).
            "onError": "continueRegularOutput",
            **_relay_call("GET", f"{messages_url}/{{{{ $json.id }}}}", query={"format": "full"}),
        },
    ]
    for n in added:
        wj.add_node(wf, {"id": wj.new_node_id(wf["name"], n["name"]), **n})
    # The search result (no messages) also goes straight on, so an empty inbox still reaches
    # "Build empty report" (via Extract article links -> noArticles); alwaysOutputData keeps n8n
    # from ending the run silently when nothing is left.
    _replace_node(
        wf,
        MEDIUM_GMAIL_NODE,
        {"position": [x + 800, y], "alwaysOutputData": True, **_code(MEDIUM_MESSAGES_JS)},
    )
    wj.connect(wf, "Build rolling 7-day window", "Search Gmail")
    wj.connect(wf, "Search Gmail", "Found Gmail messages")
    wj.connect(wf, "Found Gmail messages", "Gmail message IDs", output=0)
    wj.connect(wf, "Found Gmail messages", MEDIUM_GMAIL_NODE, output=1)
    wj.connect(wf, "Gmail message IDs", "Read Gmail message")
    wj.connect(wf, "Read Gmail message", MEDIUM_GMAIL_NODE)

    # With alwaysOutputData an empty result is one empty item: count real messages only.
    for name in ("Build Medium weekly report", "Build empty report"):
        code = wj.node(wf, name)
        code["parameters"]["jsCode"] = _replace_once(
            code["parameters"]["jsCode"],
            f"$('{MEDIUM_GMAIL_NODE}').all().length",
            f"$('{MEDIUM_GMAIL_NODE}').all().filter((item) => item.json.id).length",
            name,
        )


# ------------------------------------------------------------------------ github merge (Make)

MAKE_MERGE_WINDOW_MINUTES = 20  # > the 15-minute polling interval


def fix_github_merge_blueprint(original: Workflow) -> Workflow:
    """Make blueprint "GitHub 合并提交 Diff 通知前端", prepared for a Make Bridge template.

    Adds a filter in front of the commit lookup: only PRs that are merged (unmerged PR updates
    have no merge commit and made the scenario error) and were merged within the last
    MAKE_MERGE_WINDOW_MINUTES (the trigger watches *updated* PRs, so later activity on an old
    merged PR would otherwise post its diff again). Also removes the owner's connection IDs.
    Repo and channel stay as sample values; they become end-user inputs in the Bridge
    template (see catalog/github-merge-slack/make-setup.md).
    """
    bp = copy.deepcopy(original)
    bp["name"] = "GitHub merge → Slack (demo template)"
    modules = {m["id"]: m for m in bp["flow"]}
    _require(modules.get(1, {}).get("module") == "github:newPullRequest", "module 1 is not the PR trigger")
    _require(modules.get(2, {}).get("module") == "github:makeRestApiCall", "module 2 is not the API call")
    modules[2]["filter"] = {
        "name": "Recently merged pull requests only",
        "conditions": [
            [
                {"a": "{{1.merged}}", "b": "true", "o": "boolean:equal"},
                {
                    "a": "{{1.mergedAt}}",
                    "b": f"{{{{addMinutes(now; -{MAKE_MERGE_WINDOW_MINUTES})}}}}",
                    "o": "date:greater",
                },
            ]
        ],
    }
    for module in bp["flow"]:
        if "__IMTCONN__" in module.get("parameters", {}):
            module["parameters"]["__IMTCONN__"] = None
    return bp
