"""The uptime and Medium templates' Google calls, run in Node: the Code nodes' JavaScript and the
HTTP nodes' {{ expressions }} produce calls the Google relay accepts, and data shaped the way the
rest of each workflow (from the team's originals) expects."""

import base64
import json

import pytest

from workflow_demo.catalog import fixes
from workflow_demo.n8n import workflow_json as wj
from workflow_demo.services import google_relay

RELAY = "http://demo.internal:8000/api/google-relay"
SHEET = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abc"


@pytest.fixture
def uptime(originals):
    return fixes.fix_uptime(originals["uptime-monitor"])


@pytest.fixture
def medium(originals):
    return fixes.fix_medium_digest(originals["medium-digest"])


def item(**json_):
    return {"json": json_}


def http_call(n8n_js, wf, name, items, nodes):
    """(method, relay path, query, body) of an HTTP Request node, with expressions filled in."""
    params = wj.node(wf, name)["parameters"]

    def fill(text):
        return n8n_js(text, items, nodes, mode="expression") if text.startswith("=") else text

    url = fill(params["url"])
    assert url.startswith(f"{RELAY}/"), url
    query = [(q["name"], fill(q["value"])) for q in params.get("queryParameters", {}).get("parameters", [])]
    body = json.loads(fill(params["jsonBody"])) if params.get("sendBody") else None
    return params["method"], url.removeprefix(f"{RELAY}/"), query, body


def relay_accepts(method, path, query):
    route, match = google_relay._match(method, path)
    assert {k for k, _ in query} <= route.params, "a query parameter would be dropped by the relay"
    return route, match.groupdict()


# --------------------------------------------------------------------------- uptime monitor


def uptime_nodes(**extra):
    return {"Spreadsheet": [item(googleApi=RELAY, spreadsheetId=SHEET)], **extra}


def test_uptime_reads_the_sites_tab(n8n_js, uptime):
    method, path, query, _ = http_call(n8n_js, uptime, "Read Sites", [item()], uptime_nodes())
    route, groups = relay_accepts(method, path, query)
    assert (method, groups) == ("GET", {"sheet": SHEET, "range": "Sites!A2:B"})

    # The Sheets API's values -> one item per site, as the Google Sheets node made them.
    values = {"range": "Sites!A2:B10", "values": [["https://a.test", "UP"], [""], ["https://b.test"]]}
    code = wj.node(uptime, "Get Sites")["parameters"]["jsCode"]
    assert n8n_js(code, [item(**values)]) == [
        item(Property="https://a.test", Status="UP", row_number=2),
        item(Property="https://b.test", Status="", row_number=4),
    ]
    assert n8n_js(code, [item(range="Sites!A2:B")]) == []  # an empty tab has no "values"


def test_uptime_logs_and_updates_the_sites_row(n8n_js, uptime):
    check = item(
        date="Tue, 06 Oct 2026 10:00:00 GMT",
        Property="https://b.test",
        UP_FROM_UP=False,
        DOWN_FROM_DOWN=False,
        UP_FROM_DOWN=False,
        DOWN_FROM_UP=True,
        row_number=4,
    )
    nodes = uptime_nodes(**{"Calculate Status": [check]})
    method, path, query, body = http_call(n8n_js, uptime, "Log Uptime Event", [check], nodes)
    _, groups = relay_accepts(method, path, query)
    assert (method, groups["range"]) == ("POST", "Log!A:F")
    assert dict(query) == {"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"}
    assert body == {
        "values": [["Tue, 06 Oct 2026 10:00:00 GMT", "https://b.test", False, False, False, True]]
    }

    appended = item(spreadsheetId=SHEET, updates={"updatedRange": "Log!A5:F5"})
    method, path, query, body = http_call(n8n_js, uptime, "Update Site Status", [appended], nodes)
    _, groups = relay_accepts(method, path, query)
    assert (method, groups) == ("PUT", {"sheet": SHEET, "range": "Sites!B4"})
    assert body == {"values": [["DOWN"]]}

    back_up = {**check["json"], "DOWN_FROM_UP": False, "UP_FROM_DOWN": True}
    nodes = uptime_nodes(**{"Calculate Status": [item(**back_up)]})
    assert http_call(n8n_js, uptime, "Update Site Status", [appended], nodes)[3] == {"values": [["UP"]]}


def test_calculate_status_carries_the_row_number(uptime):
    assert fixes._assignment(wj.node(uptime, "Calculate Status"), "row_number") == {
        "id": "row-number",
        "name": "row_number",
        "type": "number",
        "value": "={{ $json.row_number }}",
    }


# --------------------------------------------------------------------------- medium digest

WINDOW = item(
    receivedAfter="2026-09-29T10:00:00.000Z",
    receivedBefore="2026-10-06T10:00:00.000Z",
    windowLabel="2026-09-29T10:00 to 2026-10-06T10:00 UTC",
    gmailSearch="Medium",
)
ARTICLE = "https://medium.com/@someone/building-agents-that-ship-0123456789ab"


def medium_nodes(**extra):
    config = item(googleApi=RELAY, slackChannel="C1", llmModel="m", freediumEndpoint="x", llmEndpoint="y")
    return {"Workflow configuration": [config], "Build rolling 7-day window": [WINDOW], **extra}


def b64url(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def gmail_message(message_id, html):
    """A Gmail API message, format=full (multipart/alternative)."""
    return {
        "id": message_id,
        "threadId": f"t-{message_id}",
        "labelIds": ["INBOX"],
        "snippet": "Today&#39;s highlights",
        "internalDate": "1791280800000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "Date", "value": "Tue, 06 Oct 2026 08:00:00 +0000"},
                {"name": "Subject", "value": "Your Medium Daily Digest"},
                {"name": "From", "value": "Medium Daily Digest <noreply@medium.com>"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"size": 5, "data": b64url("Hello")}},
                {"mimeType": "text/html", "body": {"size": len(html), "data": b64url(html)}},
            ],
        },
    }


def test_medium_searches_gmail_in_the_7_day_window(n8n_js, medium):
    method, path, query, _ = http_call(n8n_js, medium, "Search Gmail", [WINDOW], medium_nodes())
    relay_accepts(method, path, query)
    assert (method, path) == ("GET", "gmail/v1/users/me/messages")
    assert dict(query) == {"q": "Medium after:1790676000 before:1791280800", "maxResults": "20"}

    found = item(messages=[{"id": "m1", "threadId": "t1"}, {"id": "m2", "threadId": "t2"}])
    ids = n8n_js(wj.node(medium, "Gmail message IDs")["parameters"]["jsCode"], [found])
    assert ids == [item(id="m1"), item(id="m2")]
    method, path, query, _ = http_call(n8n_js, medium, "Read Gmail message", ids[:1], medium_nodes())
    _, groups = relay_accepts(method, path, query)
    assert (method, groups, query) == ("GET", {"message": "m1"}, [("format", "full")])


def test_medium_messages_feed_the_teams_link_extraction(n8n_js, medium):
    html = (
        f'<p>Top pick</p><a href="{ARTICLE}?source=email-digest">Building agents that ship to production</a>'
    )
    shaped = n8n_js(
        wj.node(medium, "Find Medium Daily Digest emails")["parameters"]["jsCode"],
        [item(**gmail_message("m1", html)), item(error={"message": "404"})],  # a deleted message is skipped
    )
    assert len(shaped) == 1
    email = shaped[0]["json"]
    assert (email["id"], email["internalDate"], email["subject"]) == (
        "m1",
        1791280800000,
        "Your Medium Daily Digest",
    )
    assert email["date"] == "Tue, 06 Oct 2026 08:00:00 +0000"

    articles = n8n_js(wj.node(medium, "Extract article links")["parameters"]["jsCode"], shaped)
    assert [a["json"]["url"] for a in articles] == [ARTICLE]
    assert articles[0]["json"]["emailTimestamp"] == 1791280800000


def test_medium_empty_inbox_gives_the_empty_report(n8n_js, medium):
    # "Found Gmail messages" sends the bare search result on; nothing is a message, and n8n's
    # alwaysOutputData turns the empty output into one empty item.
    shaped = n8n_js(
        wj.node(medium, "Find Medium Daily Digest emails")["parameters"]["jsCode"],
        [item(resultSizeEstimate=0)],
    )
    assert shaped == []
    empty_item = [item()]
    extracted = n8n_js(wj.node(medium, "Extract article links")["parameters"]["jsCode"], empty_item)
    assert extracted[0]["json"]["noArticles"] is True
    report = n8n_js(
        wj.node(medium, "Build empty report")["parameters"]["jsCode"],
        extracted,
        medium_nodes(**{"Find Medium Daily Digest emails": empty_item}),
    )
    assert "Gmail messages matched: 0" in report[0]["json"]["report"]


def test_found_gmail_messages_checks_the_count(medium):
    condition = wj.node(medium, "Found Gmail messages")["parameters"]["conditions"]["conditions"][0]
    assert condition["leftValue"] == "={{ ($json.messages || []).length }}"
    assert (condition["operator"], condition["rightValue"]) == ({"type": "number", "operation": "gt"}, 0)
