"""n8n adapter against a mocked n8n public API (respx)."""

import hashlib
import hmac
import json
import logging

import httpx
import pytest
import respx

from workflow_demo.adapters.base import AdapterError, DeployContext, OAuthTokens
from workflow_demo.adapters.n8n import N8nAdapter, summarize_execution
from workflow_demo.catalog.loader import load_catalog
from workflow_demo.n8n.client import N8nClient
from workflow_demo.n8n.transform import RUN_HEADER, RUN_NODE_NAME

N8N = "https://n8n.test"
API = f"{N8N}/api/v1"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
CATALOG = load_catalog()
UPTIME_SETTINGS = {"slack_channel": "C0123ABCD", "sites": ["https://example.com", "https://bad.example"]}


class Creds:
    """Stands in for services.connections.UserCredentials."""

    def __init__(self):
        self.calls = []

    def oauth_tokens(self, connector, *, with_refresh_token=False):
        self.calls.append((connector, with_refresh_token))
        return OAuthTokens(
            access_token=f"{connector}-access",
            refresh_token=f"{connector}-refresh" if with_refresh_token else None,
            scope="scope-a scope-b" if connector == "google" else None,
        )

    def secret_value(self, connector):
        return f"{connector}-secret"


@pytest.fixture
def adapter(make_settings):
    settings = make_settings(
        n8n_base_url=N8N,
        n8n_api_key="n8n-key",
        google_client_id="gid.apps.googleusercontent.com",
        google_client_secret="gsecret",
        openai_api_key="sk-owner",
        reader_base_url="https://reader.test/",
        reader_api_token="reader-token",
    )
    http = httpx.Client()
    return N8nAdapter(settings, N8nClient(N8N, "n8n-key", http), http)


def context(workflow_id, settings, refs=None, creds=None):
    return DeployContext(
        username="alice",
        workflow=CATALOG.workflow(workflow_id),
        deployment_id=7,
        settings=settings,
        connections={},
        refs=refs or {},
        credentials=creds or Creds(),
    )


def mock_credentials():
    """POST /credentials returns cred-1, cred-2, ... and records each request body."""
    bodies = []

    def create(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": f"cred-{len(bodies)}", "name": bodies[-1]["name"]})

    respx.post(f"{API}/credentials").mock(side_effect=create)
    return bodies


def run_token(path):
    key = hashlib.sha256(b"n8n-run:test-secret").digest()
    return hmac.new(key, path.encode(), hashlib.sha256).hexdigest()


@respx.mock
def test_deploy_uptime(adapter):
    sheet = respx.post(SHEETS).mock(
        return_value=httpx.Response(
            200, json={"spreadsheetId": "sheet-1", "spreadsheetUrl": "https://docs.google.com/s/sheet-1"}
        )
    )
    bodies = mock_credentials()
    created = respx.post(f"{API}/workflows").mock(return_value=httpx.Response(200, json={"id": "wf-1"}))
    published = respx.post(f"{API}/workflows/wf-1/publish").mock(return_value=httpx.Response(200, json={}))

    creds = Creds()
    result = adapter.deploy(context("uptime-monitor", UPTIME_SETTINGS, creds=creds))

    # Spreadsheet: Sites seeded from settings, Log header, created with the user's token.
    sheet_body = json.loads(sheet.calls.last.request.content)
    assert sheet.calls.last.request.headers["authorization"] == "Bearer google-access"
    sites_rows = sheet_body["sheets"][0]["data"][0]["rowData"]
    assert [r["values"][0]["userEnteredValue"]["stringValue"] for r in sites_rows] == [
        "Property",
        "https://example.com",
        "https://bad.example",
    ]

    # Credentials: Google with our OAuth client and the refresh token, Slack bot token, run-now header.
    by_type = {b["type"]: b for b in bodies}
    google = by_type["googleSheetsOAuth2Api"]["data"]
    assert google["clientId"] == "gid.apps.googleusercontent.com" and google["clientSecret"] == "gsecret"
    assert google["oauthTokenData"] == {
        "access_token": "google-access",
        "refresh_token": "google-refresh",
        "token_type": "Bearer",
        "scope": "scope-a scope-b",
    }
    assert by_type["slackApi"]["data"] == {"accessToken": "slack-access"}
    assert ("google", True) in creds.calls and ("slack", False) in creds.calls
    run_cred = by_type["httpHeaderAuth"]
    assert run_cred["data"]["name"] == RUN_HEADER
    assert all(b["name"].startswith("demo · alice · uptime-monitor · ") for b in bodies)

    # Workflow: filled in, credentials wired, run-now webhook, then published.
    wf = json.loads(created.calls.last.request.content)
    assert wf["name"] == "[demo] Website uptime monitor · alice"
    text = json.dumps(wf)
    assert "sheet-1" in text and "C0123ABCD" in text and "slot:" not in text
    run_node = next(n for n in wf["nodes"] if n["name"] == RUN_NODE_NAME)
    path = run_node["parameters"]["path"]
    assert run_cred["data"]["value"] == run_token(path)
    assert published.called
    assert created.calls.last.request.headers["x-n8n-api-key"] == "n8n-key"

    assert result.status == "active"
    assert result.refs == {
        "workflow_id": "wf-1",
        "credential_ids": ["cred-1", "cred-2", "cred-3"],
        "workflow_url": f"{N8N}/workflow/wf-1",
        "webhook_path": path,
        "spreadsheet_id": "sheet-1",
        "spreadsheet_url": "https://docs.google.com/s/sheet-1",
    }


@respx.mock
def test_meegle_and_medium_credentials(adapter):
    bodies = mock_credentials()
    respx.post(f"{API}/workflows").mock(return_value=httpx.Response(200, json={"id": "wf-2"}))
    respx.post(f"{API}/workflows/wf-2/publish").mock(return_value=httpx.Response(200, json={}))

    meegle = {
        "slack_channel": "C0123ABCD",
        "meegle_project_key": "p",
        "meegle_simple_name": "s",
        "window_hours": 24,
    }
    adapter.deploy(context("meegle-daily-digest", meegle))
    header = next(b for b in bodies if b["name"].endswith("meegle_mcp"))
    assert header["data"] == {"name": "X-Mcp-Token", "value": "meegle_mcp_token-secret"}

    bodies.clear()
    adapter.deploy(context("medium-digest", {"slack_channel": "C0123ABCD", "llm_model": "gpt-4o"}))
    by_type = {b["type"]: b["data"] for b in bodies}
    assert by_type["openAiApi"] == {"apiKey": "sk-owner", "url": "https://api.openai.com/v1"}
    assert by_type["gmailOAuth2"]["oauthTokenData"]["refresh_token"] == "google-refresh"
    reader = next(b for b in bodies if b["name"].endswith("· reader"))
    assert reader["data"] == {"name": "Authorization", "value": "Bearer reader-token"}


@respx.mock
def test_medium_values_point_at_shared_services(adapter):
    mock_credentials()
    created = respx.post(f"{API}/workflows").mock(return_value=httpx.Response(200, json={"id": "wf-3"}))
    respx.post(f"{API}/workflows/wf-3/publish").mock(return_value=httpx.Response(200, json={}))
    adapter.deploy(context("medium-digest", {"slack_channel": "C0123ABCD", "llm_model": "gpt-4o"}))
    text = json.dumps(json.loads(created.calls.last.request.content))
    assert "https://reader.test/extract" in text
    assert "https://api.openai.com/v1/chat/completions" in text
    assert "gpt-4o" in text and "sk-owner" not in text and "reader-token" not in text


@respx.mock
def test_publish_falls_back_to_activate(adapter):
    mock_credentials()
    respx.post(SHEETS).mock(
        return_value=httpx.Response(200, json={"spreadsheetId": "s", "spreadsheetUrl": "u"})
    )
    respx.post(f"{API}/workflows").mock(return_value=httpx.Response(200, json={"id": "wf-1"}))
    respx.post(f"{API}/workflows/wf-1/publish").mock(
        return_value=httpx.Response(404, json={"message": "nope"})
    )
    activated = respx.post(f"{API}/workflows/wf-1/activate").mock(return_value=httpx.Response(200, json={}))
    adapter.deploy(context("uptime-monitor", UPTIME_SETTINGS))
    assert activated.called


@respx.mock
def test_failed_deploy_removes_what_it_created(adapter):
    respx.post(SHEETS).mock(
        return_value=httpx.Response(200, json={"spreadsheetId": "s-9", "spreadsheetUrl": "u"})
    )
    mock_credentials()
    respx.post(f"{API}/workflows").mock(
        return_value=httpx.Response(400, json={"message": "request/body/nodes/0 has unknown property"})
    )
    deleted = respx.delete(url__regex=rf"{API}/credentials/cred-\d").mock(return_value=httpx.Response(200))
    sheet_deleted = respx.delete("https://www.googleapis.com/drive/v3/files/s-9").mock(
        return_value=httpx.Response(204)
    )
    with pytest.raises(AdapterError, match="unknown property"):
        adapter.deploy(context("uptime-monitor", UPTIME_SETTINGS))
    assert {c.request.url.path for c in deleted.calls} == {
        "/api/v1/credentials/cred-1",
        "/api/v1/credentials/cred-2",
        "/api/v1/credentials/cred-3",
    }
    assert sheet_deleted.called


@respx.mock
def test_cleanup_continues_when_a_delete_fails(adapter, caplog):
    caplog.set_level(logging.WARNING, logger="workflow_demo.adapters.n8n")
    respx.post(SHEETS).mock(
        return_value=httpx.Response(200, json={"spreadsheetId": "s-9", "spreadsheetUrl": "u"})
    )
    mock_credentials()
    respx.post(f"{API}/workflows").mock(return_value=httpx.Response(200, json={"id": "wf-5"}))
    respx.post(f"{API}/workflows/wf-5/publish").mock(
        return_value=httpx.Response(400, json={"message": "bad"})
    )
    respx.delete(f"{API}/workflows/wf-5").mock(return_value=httpx.Response(500, json={"message": "down"}))
    creds_deleted = respx.delete(url__regex=rf"{API}/credentials/.*").mock(return_value=httpx.Response(200))
    respx.delete(url__regex=r"https://www.googleapis.com/drive/v3/files/.*").mock(
        return_value=httpx.Response(204)
    )
    with pytest.raises(AdapterError):
        adapter.deploy(context("uptime-monitor", UPTIME_SETTINGS))
    assert creds_deleted.call_count == 3
    assert "workflow wf-5" in caplog.text and "google-access" not in caplog.text


@respx.mock
def test_redeploy_reuses_the_spreadsheet(adapter):
    mock_credentials()
    created = respx.post(f"{API}/workflows").mock(return_value=httpx.Response(200, json={"id": "wf-2"}))
    respx.post(f"{API}/workflows/wf-2/publish").mock(return_value=httpx.Response(200, json={}))
    new_sheet = respx.post(SHEETS).mock(
        return_value=httpx.Response(200, json={"spreadsheetId": "new", "spreadsheetUrl": "https://s/new"})
    )
    respx.get(f"{SHEETS}/old").mock(
        return_value=httpx.Response(200, json={"spreadsheetId": "old", "spreadsheetUrl": "https://s/old"})
    )
    ctx = DeployContext(
        username="alice",
        workflow=CATALOG.workflow("uptime-monitor"),
        deployment_id=7,
        settings=UPTIME_SETTINGS,
        connections={},
        refs={},
        credentials=Creds(),
        previous_refs={"spreadsheet_id": "old", "workflow_id": "wf-1"},
    )
    result = adapter.deploy(ctx)
    assert not new_sheet.called
    assert result.refs["spreadsheet_id"] == "old" and result.refs["spreadsheet_url"] == "https://s/old"
    assert "old" in json.dumps(json.loads(created.calls.last.request.content))

    # The user deleted it: a new one is made.
    respx.get(f"{SHEETS}/old").mock(return_value=httpx.Response(404, json={}))
    assert adapter.deploy(ctx).refs["spreadsheet_id"] == "new"


@respx.mock
def test_google_is_read_once_per_deploy(adapter):
    respx.post(SHEETS).mock(
        return_value=httpx.Response(200, json={"spreadsheetId": "s", "spreadsheetUrl": "u"})
    )
    mock_credentials()
    respx.post(f"{API}/workflows").mock(return_value=httpx.Response(200, json={"id": "wf-1"}))
    respx.post(f"{API}/workflows/wf-1/publish").mock(return_value=httpx.Response(200, json={}))
    creds = Creds()
    adapter.deploy(context("uptime-monitor", UPTIME_SETTINGS, creds=creds))
    assert creds.calls == [("google", True), ("slack", False)]


def test_catalog_needs_only_supported_items(adapter):
    for entry in CATALOG.workflows:
        if entry.n8n:
            assert not [m for m in adapter.missing_config(entry) if m.startswith("support")], entry.id


@respx.mock
def test_failed_publish_removes_the_workflow(adapter):
    mock_credentials()
    respx.post(f"{API}/workflows").mock(return_value=httpx.Response(200, json={"id": "wf-5"}))
    respx.post(f"{API}/workflows/wf-5/publish").mock(
        return_value=httpx.Response(400, json={"message": "Workflow has issues"})
    )
    wf_deleted = respx.delete(f"{API}/workflows/wf-5").mock(return_value=httpx.Response(200))
    respx.delete(url__regex=rf"{API}/credentials/.*").mock(return_value=httpx.Response(200))
    meegle = {
        "slack_channel": "C0123ABCD",
        "meegle_project_key": "p",
        "meegle_simple_name": "s",
        "window_hours": 24,
    }
    with pytest.raises(AdapterError, match="Workflow has issues"):
        adapter.deploy(context("meegle-daily-digest", meegle))
    assert wf_deleted.called


@respx.mock
def test_connection_problem_stops_before_n8n(adapter):
    class NoGoogle(Creds):
        def oauth_tokens(self, connector, *, with_refresh_token=False):
            raise AdapterError("Connect Google (Sheets and Gmail) first")

    credential_calls = respx.post(f"{API}/credentials")
    with pytest.raises(AdapterError, match="Connect Google"):
        adapter.deploy(context("uptime-monitor", UPTIME_SETTINGS, creds=NoGoogle()))
    assert not credential_calls.called


def test_availability_lists_missing_configuration(make_settings):
    settings = make_settings(n8n_base_url=N8N, n8n_api_key="k")
    http = httpx.Client()
    adapter = N8nAdapter(settings, N8nClient(N8N, "k", http), http)
    assert adapter.check_available(CATALOG.workflow("meegle-daily-digest")).available
    uptime = adapter.check_available(CATALOG.workflow("uptime-monitor"))
    assert not uptime.available and "GOOGLE_CLIENT_ID" in uptime.reason
    medium = adapter.check_available(CATALOG.workflow("medium-digest"))
    assert "OPENAI_API_KEY" in medium.reason and "READER_BASE_URL" in medium.reason
    with pytest.raises(AdapterError, match="Not set up"):
        adapter.deploy(context("medium-digest", {"slack_channel": "C0123ABCD"}))


@respx.mock
def test_run_now_calls_the_webhook(adapter):
    hook = respx.post(f"{N8N}/webhook/path-1").mock(
        return_value=httpx.Response(200, json={"message": "Workflow was started"})
    )
    started = adapter.run_now(context("uptime-monitor", UPTIME_SETTINGS, refs={"webhook_path": "path-1"}))
    assert hook.calls.last.request.headers[RUN_HEADER.lower()] == run_token("path-1")
    assert started.run_id is None and "Run started" in started.message

    respx.post(f"{N8N}/webhook/path-1").mock(
        return_value=httpx.Response(404, json={"message": "not registered"})
    )
    with pytest.raises(AdapterError, match="redeploy"):
        adapter.run_now(context("uptime-monitor", UPTIME_SETTINGS, refs={"webhook_path": "path-1"}))
    with pytest.raises(AdapterError, match="no Run now"):
        adapter.run_now(context("uptime-monitor", UPTIME_SETTINGS))


@respx.mock
def test_undeploy_removes_workflow_and_credentials(adapter):
    wf = respx.delete(f"{API}/workflows/wf-1").mock(return_value=httpx.Response(404, json={}))
    creds = respx.delete(url__regex=rf"{API}/credentials/.*").mock(return_value=httpx.Response(200))
    refs = {"workflow_id": "wf-1", "credential_ids": ["c1", "c2"]}
    adapter.undeploy(context("uptime-monitor", UPTIME_SETTINGS, refs=refs))
    assert wf.called and creds.call_count == 2

    respx.delete(f"{API}/workflows/wf-1").mock(return_value=httpx.Response(500, json={"message": "boom"}))
    with pytest.raises(AdapterError, match="boom"):
        adapter.undeploy(context("uptime-monitor", UPTIME_SETTINGS, refs=refs))


def uptime_execution():
    def run(prop, **flags):
        return {"data": {"main": [[{"json": {"Property": prop, **flags}}]]}}

    return {
        "id": "101",
        "status": "success",
        "startedAt": "2026-10-04T05:00:00.000Z",
        "stoppedAt": "2026-10-04T05:00:09.000Z",
        "data": {
            "resultData": {
                "runData": {
                    "Calculate Status": [
                        run("https://example.com", UP_FROM_UP=True),
                        run("https://bad.example", DOWN_FROM_UP=True),
                    ]
                }
            }
        },
    }


@respx.mock
def test_recent_runs(adapter):
    failed = {
        "id": "100",
        "status": "error",
        "startedAt": "2026-10-04T04:00:00.000Z",
        "stoppedAt": "2026-10-04T04:00:01.000Z",
        "data": {"resultData": {"runData": {}, "error": {"message": "Sheet not found"}}},
    }
    listed = [
        {k: v for k, v in e.items() if k != "data"}
        for e in (uptime_execution(), failed, {"id": "99", "status": "running"})
    ]
    route = respx.get(f"{API}/executions").mock(return_value=httpx.Response(200, json={"data": listed}))
    detail_101 = respx.get(f"{API}/executions/101").mock(
        return_value=httpx.Response(200, json=uptime_execution())
    )
    detail_100 = respx.get(f"{API}/executions/100").mock(return_value=httpx.Response(200, json=failed))
    ctx = context("uptime-monitor", UPTIME_SETTINGS, refs={"workflow_id": "wf-1"})

    runs = adapter.recent_runs(ctx)
    params = route.calls.last.request.url.params
    assert params["workflowId"] == "wf-1" and "includeData" not in params  # list stays small
    assert detail_101.calls.last.request.url.params["includeData"] == "true"
    assert runs[0].summary == "https://example.com is UP\nhttps://bad.example is DOWN (alert sent)"
    assert runs[0].status == "success" and runs[0].finished_at.second == 9
    assert runs[1].status == "error" and runs[1].error == "Sheet not found"
    assert runs[2].status == "running" and runs[2].summary is None
    assert adapter.recent_runs(context("uptime-monitor", UPTIME_SETTINGS)) == []

    # Finished executions are summarized once; polling doesn't download their data again.
    assert adapter.recent_runs(ctx) == runs
    assert detail_101.call_count == 1 and detail_100.call_count == 1


def test_summaries_for_text_reports():
    execution = {
        "id": "5",
        "status": "success",
        "data": json.dumps(
            {
                "resultData": {
                    "runData": {
                        "Build empty report": [{"data": {"main": [[{"json": {"report": "# Empty"}}]]}}]
                    }
                }
            }
        ),
    }
    nodes = CATALOG.workflow("medium-digest").n8n.result_nodes
    assert summarize_execution(execution, nodes).summary == "# Empty"
    digest = {
        "id": "6",
        "status": "success",
        "data": {
            "resultData": {
                "runData": {
                    "Compose digest": [{"data": {"main": [[{"json": {"text": "📊 日报" + "x" * 5000}}]]}}]
                }
            }
        },
    }
    summary = summarize_execution(digest, ["Compose digest"]).summary
    assert summary.startswith("📊 日报") and len(summary) == 4000
    assert summarize_execution({"id": "7", "status": "canceled"}, []).error == "Canceled"
