"""Admin endpoints: setup check, sweep now, stopping a tester's deployment."""

import base64

import httpx
import pytest
import respx

ADMIN = {"passcode": "adminpass"}


@pytest.fixture
def admin(client, login):
    login("alice")
    client.post("/api/connections/google/fake")
    client.post("/api/connections/slack/fake")
    client.post("/api/deployments/uptime-monitor", json={"settings": {"slack_channel": "C0123ABCD"}})
    assert client.post("/api/admin/login", json=ADMIN).status_code == 204
    return client


def test_admin_endpoints_need_the_admin_cookie(client):
    assert client.get("/api/admin/setup").status_code == 401
    assert client.post("/api/admin/sweep").status_code == 401
    assert client.post("/api/admin/users/alice/deployments/uptime-monitor/stop").status_code == 401


def test_setup_check_in_fake_mode(admin):
    data = admin.get("/api/admin/setup").json()
    checks = {c["name"]: c for c in data["checks"]}
    assert checks["Database"]["state"] == "ok"
    assert checks["Mode"]["state"] == "info"
    assert checks["Nango"]["state"] == "missing" and "NANGO_SECRET_KEY" in checks["Nango"]["detail"]
    assert checks["n8n"]["state"] == "missing"
    assert {w["id"]: w["available"] for w in data["workflows"]}["uptime-monitor"] is True


def test_sweep_now(admin):
    report = admin.post("/api/admin/sweep").json()
    assert report == {
        "stopped": [],
        "recovered_jobs": 0,
        "orphans_removed": [],
        "errors": [],
        "orphan_sweep": False,
    }


def test_stop_a_testers_deployment(admin):
    assert admin.post("/api/admin/users/alice/deployments/uptime-monitor/stop").json() == {
        "status": "stopped"
    }
    events = admin.get("/api/workflows/uptime-monitor").json()["deployment"]["events"]
    assert any(e["message"] == "Stopped by the admin" for e in events)
    assert admin.post("/api/admin/users/nobody/deployments/uptime-monitor/stop").status_code == 404
    assert admin.post("/api/admin/users/alice/deployments/medium-digest/stop").status_code == 404


@pytest.fixture
def live_admin(make_settings):
    from fastapi.testclient import TestClient

    from workflow_demo.app import build_services, create_app

    settings = make_settings(
        DEMO_FAKE_PLATFORMS=False,
        nango_secret_key="nango",
        nango_host="https://nango.test",
        data_encryption_key=base64.b64encode(b"k" * 32).decode(),
        n8n_base_url="https://n8n.test",
        n8n_api_key="n8n-key",
        relay_base_url="http://demo.internal:8000",
        openai_api_key="sk-x",
        reader_base_url="https://reader.test",
        reader_api_token="r",
        bot_api_token="b",
    )
    svc = build_services(settings)
    svc.db.create_all()
    with TestClient(create_app(settings, svc)) as client:
        client.post("/api/admin/login", json=ADMIN)
        yield client


@respx.mock
def test_setup_check_with_live_services(live_admin):
    respx.get("https://nango.test/integrations").mock(
        return_value=httpx.Response(200, json={"data": [{"unique_key": "slack"}]})
    )
    respx.get("https://n8n.test/api/v1/workflows").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get("https://api.openai.com/v1/models").mock(return_value=httpx.Response(401, json={}))
    respx.get("https://reader.test/healthz").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    respx.get("http://demo.internal:8000/api/google-relay/check").mock(
        return_value=httpx.Response(401, json={"error": {"code": 401, "message": "Invalid Google relay key"}})
    )
    checks = {c["name"]: c for c in live_admin.get("/api/admin/setup").json()["checks"]}
    assert checks["Nango"]["state"] == "error" and "google" in checks["Nango"]["detail"]
    assert checks["Encryption key"]["state"] == "ok"
    assert checks["n8n"]["state"] == "ok"
    assert checks["Google relay"]["state"] == "ok"
    assert "http://demo.internal:8000/api/google-relay" in checks["Google relay"]["detail"]
    assert checks["LLM API"]["state"] == "error" and "401" in checks["LLM API"]["detail"]
    assert checks["Medium reader"]["state"] == "ok"
    assert checks["Make Bridge"]["state"] == "missing"
    assert checks["Slack bot"]["state"] == "ok"
    assert "Mode" not in checks


@respx.mock
def test_setup_check_reports_a_relay_url_that_isnt_the_demo(live_admin):
    # e.g. RELAY_BASE_URL left at the public address, where Caddy doesn't offer the relay.
    respx.get("http://demo.internal:8000/api/google-relay/check").mock(
        return_value=httpx.Response(404, text="nope")
    )
    respx.route().mock(return_value=httpx.Response(200, json={"data": []}))
    checks = {c["name"]: c for c in live_admin.get("/api/admin/setup").json()["checks"]}
    assert checks["Google relay"]["state"] == "error" and "404" in checks["Google relay"]["detail"]
    assert "RELAY_BASE_URL" in checks["Google relay"]["detail"]


def test_setup_check_reaches_the_real_relay(client, make_settings):
    # The probe's expectation matches what the relay really answers without a key.
    resp = client.get("/api/google-relay/check")
    assert resp.status_code == 401
    assert resp.json() == {"error": {"code": 401, "message": "Invalid Google relay key"}}
