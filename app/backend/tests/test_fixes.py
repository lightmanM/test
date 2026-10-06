import json
import re

from workflow_demo import paths
from workflow_demo.catalog import fixes
from workflow_demo.catalog.build import targets
from workflow_demo.catalog.loader import load_catalog
from workflow_demo.n8n import workflow_json as wj

SECRET_PATTERNS = [
    re.compile(r"m-AB-[0-9a-f]{8}-"),  # Meegle MCP token
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),  # Slack token
    re.compile(r"hooks\.slack\.com/services/[A-Z0-9]"),  # Slack webhook
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI key
]


def assert_no_secrets(data):
    text = json.dumps(data, ensure_ascii=False)
    for pattern in SECRET_PATTERNS:
        assert not pattern.search(text), pattern.pattern


def test_uptime_unreachable_site_counts_as_down(originals):
    # Tester report: a site that doesn't answer made "Perform Site Test" throw ("The connection timed
    # out"), so the whole run failed and no DOWN alert was sent.
    wf = fixes.fix_uptime(originals["uptime-monitor"])
    check = wj.node(wf, "Perform Site Test")
    assert check["onError"] == "continueRegularOutput"  # the failed request still reaches Calculate Status
    assert check["parameters"]["options"]["timeout"] == fixes.UPTIME_SITE_TIMEOUT_MS
    assert check["parameters"]["options"]["response"]["response"]["neverError"] is True  # 4xx/5xx kept
    calc = wj.node(wf, "Calculate Status")
    reachable = "($json.statusCode > 0 && $json.statusCode < 400)"
    expected = {
        "UP_FROM_UP": f"={{{{ {reachable} && $json.Status !== 'DOWN' }}}}",
        "DOWN_FROM_DOWN": f"={{{{ !{reachable} && $json.Status === 'DOWN' }}}}",
        "UP_FROM_DOWN": f"={{{{ {reachable} && $json.Status === 'DOWN' }}}}",
        "DOWN_FROM_UP": f"={{{{ !{reachable} && $json.Status !== 'DOWN' }}}}",
    }
    for name, value in expected.items():
        assert fixes._assignment(calc, name)["value"] == value, name
    # No response, no Date header: fall back to the run's own time.
    assert fixes._assignment(calc, "date")["value"] == "={{ $json.headers?.date ?? $now.toUTC().toHTTP() }}"


def test_uptime_fix(originals):
    wf = fixes.fix_uptime(originals["uptime-monitor"])
    assert wf["name"] == "Uptime monitor (demo)"
    assert not wj.has_node(wf, "Send Email Alert1")
    interval = wj.node(wf, "Schedule Trigger")["parameters"]["rule"]["interval"][0]
    assert interval == {"field": "minutes", "minutesInterval": 30}
    assert "headerParameters" not in wj.node(wf, "Perform Site Test")["parameters"]
    assert wj.node(wf, "For Each Site...")["parameters"]["batchSize"] == 1

    calc = {
        a["name"]: a["value"]
        for a in wj.node(wf, "Calculate Status")["parameters"]["assignments"]["assignments"]
    }
    assert "$json.Status !== 'DOWN'" in calc["UP_FROM_UP"]
    assert "$json.Status !== 'DOWN'" in calc["DOWN_FROM_UP"]
    assert "$json.Status === 'DOWN'" in calc["UP_FROM_DOWN"]
    assert "$json.Status === 'DOWN'" in calc["DOWN_FROM_DOWN"]

    # No Google node is left: Sheets calls go through the demo's Google relay.
    assert not [n for n in wf["nodes"] if n["type"].startswith("n8n-nodes-base.google")]
    config = {
        a["name"]: a["value"] for a in wj.node(wf, "Spreadsheet")["parameters"]["assignments"]["assignments"]
    }
    assert config == {"googleApi": "__VALUE:google_api__", "spreadsheetId": "__VALUE:spreadsheet_id__"}
    assert wj.targets(wf, "Schedule Trigger") == ["Spreadsheet"]
    assert wj.targets(wf, "Spreadsheet") == ["Read Sites"]
    assert wj.targets(wf, "Read Sites") == ["Get Sites"]
    assert wj.targets(wf, "Get Sites") == ["For Each Site..."]
    assert wj.targets(wf, "Log Uptime Event") == ["Update Site Status"]
    assert wj.targets(wf, "Update Site Status") == ["For Each Site..."]
    for name in ("Read Sites", "Log Uptime Event", "Update Site Status"):
        params = wj.node(wf, name)["parameters"]
        assert params["authentication"] == "genericCredentialType", name
        assert params["genericAuthType"] == "httpHeaderAuth", name
    for name in ("Spreadsheet", "Read Sites", "Get Sites"):  # stable ids for added/replaced nodes
        assert wj.node(wf, name)["id"]
    assert wj.node(wf, "Get Sites")["id"] == wj.node(originals["uptime-monitor"], "Get Sites")["id"]

    slack = wj.node(wf, "Send Chat Alert")
    assert slack["parameters"]["authentication"] == "accessToken"
    assert slack["parameters"]["channelId"]["value"] == "__VALUE:slack_channel__"
    assert "'still DOWN' : 'back UP'" in slack["parameters"]["text"]
    assert sorted(wj.credential_slots(wf)) == sorted(
        [
            ("Read Sites", "httpHeaderAuth", "google"),
            ("Log Uptime Event", "httpHeaderAuth", "google"),
            ("Update Site Status", "httpHeaderAuth", "google"),
            ("Send Chat Alert", "slackApi", "slack"),
        ]
    )
    assert "pinData" not in wf and "meta" not in wf
    assert_no_secrets(wf)


def test_meegle_digest_fix(originals):
    wf = fixes.fix_meegle_digest(originals["meegle-daily-digest"])
    assignments = {
        a["name"]: a["value"] for a in wj.node(wf, "Config")["parameters"]["assignments"]["assignments"]
    }
    assert "meegle_mcp_token" not in assignments
    assert assignments["delivery_mode"] == "slack"
    assert "slack_webhook_url" not in assignments
    assert assignments["slack_channel"] == "__VALUE:slack_channel__"
    assert assignments["meegle_project_key"] == "__VALUE:meegle_project_key__"

    for name in fixes.MEEGLE_MCP_NODES:
        params = wj.node(wf, name)["parameters"]
        assert all(h["name"] != "X-Mcp-Token" for h in params["headerParameters"]["parameters"])
        assert params["authentication"] == "genericCredentialType"
        assert params["genericAuthType"] == "httpHeaderAuth"

    assert not wj.has_node(wf, "POST to Slack webhook")
    assert wj.targets(wf, "Compose digest") == ["Done (log only)", "Has Slack channel"]
    assert wj.targets(wf, "Has Slack channel") == ["Post digest to Slack"]
    post = wj.node(wf, "Post digest to Slack")["parameters"]
    assert post["authentication"] == "accessToken"
    assert post["channelId"]["value"] == "__VALUE:slack_channel__"
    assert sorted(wj.credential_slots(wf)) == [
        ("MCP: fetch bugs (issue)", "httpHeaderAuth", "meegle_mcp"),
        ("MCP: fetch stories", "httpHeaderAuth", "meegle_mcp"),
        ("Post digest to Slack", "slackApi", "slack"),
    ]
    assert all(n["id"] == wj.new_node_id(wf["name"], n["name"]) for n in wf["nodes"])
    assert wf["settings"]["executionOrder"] == "v1"
    assert_no_secrets(wf)


def test_medium_digest_fix(originals):
    wf = fixes.fix_medium_digest(originals["medium-digest"])
    code = wj.node(wf, "Extract article links")["parameters"]["jsCode"]
    assert ".slice(0, 5)" in code and ".slice(0, 100)" not in code

    reader = wj.node(wf, "Fetch article through Freedium")["parameters"]
    assert "timeoutMs: 45000" in reader["jsonBody"]
    assert reader["options"]["timeout"] == 60_000
    assert reader["genericAuthType"] == "httpHeaderAuth"
    assert wj.node(wf, "Classify and summarize article")["parameters"]["options"]["timeout"] == 60_000

    config = {
        a["name"]: a["value"]
        for a in wj.node(wf, "Workflow configuration")["parameters"]["assignments"]["assignments"]
    }
    assert config == {
        "freediumEndpoint": "__VALUE:reader_url__",
        "llmEndpoint": "__VALUE:llm_endpoint__",
        "llmModel": "__VALUE:llm_model__",
        "slackChannel": "__VALUE:slack_channel__",
        "googleApi": "__VALUE:google_api__",
    }
    # Gmail goes through the demo's Google relay: search, read each message, reshape.
    assert not [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.gmail"]
    assert wj.targets(wf, "Build rolling 7-day window") == ["Search Gmail"]
    assert wj.targets(wf, "Search Gmail") == ["Found Gmail messages"]
    assert wj.targets(wf, "Found Gmail messages", output=0) == ["Gmail message IDs"]
    assert wj.targets(wf, "Found Gmail messages", output=1) == ["Find Medium Daily Digest emails"]
    assert wj.targets(wf, "Gmail message IDs") == ["Read Gmail message"]
    assert wj.targets(wf, "Read Gmail message") == ["Find Medium Daily Digest emails"]
    assert wj.targets(wf, "Find Medium Daily Digest emails") == ["Extract article links"]
    assert sorted(wj.credential_slots(wf)) == [
        ("Classify and summarize article", "openAiApi", "openai"),
        ("Fetch article through Freedium", "httpHeaderAuth", "reader"),
        ("Read Gmail message", "httpHeaderAuth", "google"),
        ("Search Gmail", "httpHeaderAuth", "google"),
        ("Send report to Slack", "slackApi", "slack"),
    ]
    assert_no_secrets(wf)


def test_medium_digest_reports_an_empty_inbox(originals):
    # Without "Always output data" n8n ends the run when Gmail finds nothing, so the
    # "Build empty report" branch (reached through Extract article links → noArticles) never runs.
    wf = fixes.fix_medium_digest(originals["medium-digest"])
    assert wj.node(wf, "Find Medium Daily Digest emails").get("alwaysOutputData") is True
    # ...and that empty item isn't counted as an email.
    for name in ("Build Medium weekly report", "Build empty report"):
        code = wj.node(wf, name)["parameters"]["jsCode"]
        assert "$('Find Medium Daily Digest emails').all().filter((item) => item.json.id).length" in code


def test_github_blueprint_fix(originals):
    bp = fixes.fix_github_merge_blueprint(originals["github-merge-slack"])
    flow = {m["id"]: m for m in bp["flow"]}
    assert flow[2]["filter"]["conditions"] == [
        [
            {"a": "{{1.merged}}", "b": "true", "o": "boolean:equal"},
            {"a": "{{1.mergedAt}}", "b": "{{addMinutes(now; -20)}}", "o": "date:greater"},
        ]
    ]
    assert all(m["parameters"].get("__IMTCONN__", None) is None for m in bp["flow"])
    assert (
        originals["github-merge-slack"]["flow"][0]["parameters"]["__IMTCONN__"] is not None
    )  # original untouched


def test_committed_templates_are_up_to_date(load_json):
    for target in targets():
        assert load_json(target.output) == target.build(), (
            f"{target.output} is stale: run scripts/build_catalog.py"
        )


def test_catalog_sources_match_build_targets():
    catalog = load_catalog()
    for target in targets():
        assert catalog.workflow(target.workflow_id).source == str(target.source.relative_to(paths.REPO_ROOT))


def test_catalog_has_no_secrets():
    for path in paths.CATALOG_DIR.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".yaml", ".md"}:
            text = path.read_text(encoding="utf-8")
            for pattern in SECRET_PATTERNS:
                assert not pattern.search(text), f"{path}: {pattern.pattern}"
