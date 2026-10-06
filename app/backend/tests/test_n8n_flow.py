"""Through the API with the real adapters: Nango and n8n mocked, jobs run inline."""

import base64
import json

import httpx
import pytest
import respx

from workflow_demo.db import Connection, Deployment, User

NANGO = "https://nango.test"
N8N = "https://n8n.test"
API = f"{N8N}/api/v1"
KEY = base64.b64encode(b"k" * 32).decode()
UPTIME = {"slack_channel": "C0123ABCD", "sites": ["https://example.com"]}
SHEET = "1UptimeSheetId_0123456789abcdefghijklmnopq"


@pytest.fixture
def real(make_settings):
    from fastapi.testclient import TestClient

    from workflow_demo.app import build_services, create_app
    from workflow_demo.services.jobs import InlineJobRunner

    settings = make_settings(
        DEMO_FAKE_PLATFORMS=False,
        nango_secret_key="nango-secret",
        nango_host=NANGO,
        data_encryption_key=KEY,
        n8n_base_url=N8N,
        n8n_api_key="n8n-key",
    )
    svc = build_services(settings, runner_factory=InlineJobRunner)
    svc.db.create_all()
    with TestClient(create_app(settings, svc)) as client:
        client.post("/api/auth/login", json={"username": "alice", "passcode": "pass"})
        yield svc, client


def connect(client, connector, connection_id, credentials):
    respx.get(f"{NANGO}/connections/{connection_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "connection_id": connection_id,
                "provider_config_key": connector,
                "provider": connector,
                "tags": {"end_user_id": "alice"},
                "credentials": credentials,
            },
        )
    )
    resp = client.post(f"/api/connections/{connector}/complete", json={"connection_id": connection_id})
    assert resp.status_code == 200, resp.text


@respx.mock
def test_uptime_deploy_run_and_delete(real):
    svc, client = real
    respx.get(f"{NANGO}/proxy/oauth2/v3/userinfo").mock(
        return_value=httpx.Response(200, json={"email": "alice@acme.dev"})
    )
    connect(client, "google", "g-1", {"access_token": "ya29", "raw": {"scope": "s"}})
    connect(client, "slack", "s-1", {"access_token": "xoxb-1", "raw": {"team": {"name": "Acme"}}})

    catalog = {w["id"]: w for w in client.get("/api/workflows").json()}
    assert catalog["uptime-monitor"]["available"] and catalog["uptime-monitor"]["ready"]
    assert not catalog["github-merge-slack"]["available"]
    assert "MAKE_BRIDGE_KEY_ID" in catalog["github-merge-slack"]["unavailable_reason"]
    assert not catalog["medium-digest"]["available"]  # no OpenAI key / reader yet

    respx.post(f"{NANGO}/proxy/v4/spreadsheets").mock(
        return_value=httpx.Response(
            200,
            json={
                "spreadsheetId": SHEET,
                "spreadsheetUrl": f"https://docs.google.com/spreadsheets/d/{SHEET}",
            },
        )
    )
    credentials = []

    def create_credential(request):
        credentials.append(json.loads(request.content))
        return httpx.Response(200, json={"id": f"c{len(credentials)}"})

    respx.post(f"{API}/credentials").mock(side_effect=create_credential)
    respx.post(f"{API}/workflows").mock(return_value=httpx.Response(200, json={"id": "wf-9"}))
    respx.post(f"{API}/workflows/wf-9/publish").mock(return_value=httpx.Response(200, json={}))

    assert client.post("/api/deployments/uptime-monitor", json={"settings": UPTIME}).status_code == 202
    detail = client.get("/api/workflows/uptime-monitor").json()
    assert detail["deployment"]["status"] == "active", detail["deployment"]
    assert detail["deployment"]["links"] == [
        {"label": "Your uptime spreadsheet", "url": f"https://docs.google.com/spreadsheets/d/{SHEET}"}
    ]
    assert "ya29" not in json.dumps(credentials)  # n8n gets no Google token...
    relay = next(c for c in credentials if c["name"].endswith("· google"))["data"]  # ...only a relay key
    assert next(c for c in credentials if c["type"] == "slackApi")["data"] == {"accessToken": "xoxb-1"}
    # Tokens are never stored by the demo, only the n8n IDs.
    with svc.db.session() as db:
        refs = db.query(Deployment).one().platform_refs
        text = json.dumps(refs)
        assert "ya29" not in text and "xoxb" not in text and relay["value"].split(".")[1] not in text
        assert refs["credential_ids"] == ["c1", "c2", "c3"]

    # The workflow reads its Sites tab the way n8n does: through the relay, then Nango's proxy.
    values = respx.get(url__regex=rf"{NANGO}/proxy/v4/spreadsheets/{SHEET}/values/.*").mock(
        return_value=httpx.Response(200, json={"values": [["https://example.com"]]})
    )
    sites = f"/api/google-relay/sheets/v4/spreadsheets/{SHEET}/values/Sites!A2:B"
    resp = client.get(sites, headers={relay["name"]: relay["value"]})
    assert resp.status_code == 200 and resp.json() == {"values": [["https://example.com"]]}
    upstream = values.calls.last.request
    assert (upstream.headers["connection-id"], upstream.headers["authorization"]) == (
        "g-1",
        "Bearer nango-secret",
    )
    assert (
        client.get(
            sites, headers={"Authorization": "Bearer 1.wrong-key-wrong-key-wrong-key-wrong"}
        ).status_code
        == 401
    )

    respx.post(url__regex=rf"{N8N}/webhook/.*").mock(return_value=httpx.Response(200, json={}))
    assert client.post("/api/deployments/uptime-monitor/run").status_code == 202
    execution = {
        "id": "1",
        "status": "success",
        "startedAt": "2026-10-04T05:00:00Z",
        "stoppedAt": "2026-10-04T05:00:03Z",
    }
    respx.get(f"{API}/executions").mock(return_value=httpx.Response(200, json={"data": [execution]}))
    run_data = {"Calculate Status": [{"data": {"main": [[{"json": {"Property": "https://example.com"}}]]}}]}
    respx.get(f"{API}/executions/1").mock(
        return_value=httpx.Response(200, json={**execution, "data": {"resultData": {"runData": run_data}}})
    )
    runs = client.get("/api/deployments/uptime-monitor/runs").json()
    assert runs[0]["summary"] == "https://example.com is UP"

    wf_deleted = respx.delete(f"{API}/workflows/wf-9").mock(return_value=httpx.Response(200))
    cred_deleted = respx.delete(url__regex=rf"{API}/credentials/c\d").mock(return_value=httpx.Response(200))
    assert client.delete("/api/deployments/uptime-monitor").status_code == 202
    assert client.get("/api/workflows/uptime-monitor").json()["deployment"]["status"] == "stopped"
    assert wf_deleted.called and cred_deleted.call_count == 3
    # A deleted deployment's relay key no longer works.
    resp = client.get(sites, headers={relay["name"]: relay["value"]})
    assert resp.status_code == 401 and values.call_count == 1


def test_n8n_settings_must_stay_literal(real):
    svc, client = real
    resp = client.post(
        "/api/deployments/meegle-daily-digest",
        json={
            "settings": {
                "slack_channel": "C0123ABCD",
                "meegle_project_key": "={{ $env.N8N_ENCRYPTION_KEY }}",
                "meegle_simple_name": "space",
            }
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["fields"] == {"meegle_project_key": "can't start with '='"}


@respx.mock
def test_deploy_fails_clearly_without_real_connections(real):
    svc, client = real
    # Connections made with demo data before real platforms were configured.
    with svc.db.session() as db:
        user = db.query(User).one()
        for connector in ("google", "slack"):
            db.add(Connection(user_id=user.id, connector=connector, method="fake", details={}))
        db.commit()
    client.post("/api/deployments/uptime-monitor", json={"settings": UPTIME})
    dep = client.get("/api/workflows/uptime-monitor").json()["deployment"]
    assert dep["status"] == "failed"
    assert "connected with demo data" in dep["error"]
