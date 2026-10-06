"""The Google relay: n8n's calls reach Google through Nango's proxy only with a live deployment's
key, only for that workflow's calls, and only on the deployment's own spreadsheet."""

from datetime import timedelta

import httpx
import pytest
import respx

from workflow_demo import google
from workflow_demo.db import Connection, Deployment, User, utcnow
from workflow_demo.nango import NangoClient
from workflow_demo.relay_keys import KEY_REF, new_key

NANGO = "https://nango.test"
PROXY = f"{NANGO}/proxy"
SHEET = "1UptimeSheetId_0123456789abcdefghijklmnopq"
OTHER_SHEET = "1SomeoneElsesSheet_0123456789abcdefghijkl"


@pytest.fixture
def relay(make_settings):
    from fastapi.testclient import TestClient

    from workflow_demo.app import build_services, create_app

    settings = make_settings(DEMO_FAKE_PLATFORMS=False, nango_secret_key="nango-secret", nango_host=NANGO)
    svc = build_services(settings)
    svc.db.create_all()
    with svc.db.session() as db:
        user = User(username="alice")
        user.connections.append(
            Connection(
                connector="google", method="nango", nango_integration="google", nango_connection_id="g-1"
            )
        )
        db.add(user)
        db.commit()
    keys = {}
    for workflow_id in ("uptime-monitor", "medium-digest"):
        key, digest = new_key(0)  # replaced below once the row has its id
        with svc.db.session() as db:
            dep = Deployment(
                user_id=1,
                workflow_id=workflow_id,
                status="active",
                expires_at=utcnow() + timedelta(hours=1),
            )
            db.add(dep)
            db.commit()
            key, digest = new_key(dep.id)
            dep.platform_refs = {KEY_REF: digest, "spreadsheet_id": SHEET}
            db.commit()
        keys[workflow_id] = key
    with TestClient(create_app(settings, svc)) as client:
        yield svc, client, keys


def auth(key):
    return {"Authorization": f"Bearer {key}"}


def update_deployment(svc, workflow_id, **changes):
    with svc.db.session() as db:
        dep = db.query(Deployment).filter_by(workflow_id=workflow_id).one()
        for name, value in changes.items():
            setattr(dep, name, value)
        db.commit()


VALUES = f"/api/google-relay/sheets/v4/spreadsheets/{SHEET}/values"
MESSAGES = "/api/google-relay/gmail/v1/users/me/messages"


@respx.mock
def test_sheets_calls_go_to_nango_as_the_users_connection(relay):
    svc, client, keys = relay
    read = respx.get(f"{PROXY}/v4/spreadsheets/{SHEET}/values/Sites%21A2%3AB").mock(
        return_value=httpx.Response(200, json={"values": [["https://a.test", "UP"]]})
    )
    resp = client.get(
        f"{VALUES}/Sites!A2:B",
        params={"majorDimension": "ROWS", "access_token": "x", "key": "y"},
        headers=auth(keys["uptime-monitor"]),
    )
    assert resp.status_code == 200 and resp.json() == {"values": [["https://a.test", "UP"]]}
    upstream = read.calls.last.request
    assert upstream.headers["authorization"] == "Bearer nango-secret"
    assert upstream.headers["connection-id"] == "g-1" and upstream.headers["provider-config-key"] == "google"
    assert upstream.headers["base-url-override"] == "https://sheets.googleapis.com"
    assert dict(upstream.url.params) == {"majorDimension": "ROWS"}  # anything else is dropped
    assert "x-demo" not in str(upstream.headers).lower() and keys["uptime-monitor"] not in str(
        upstream.headers
    )

    append = respx.post(f"{PROXY}/v4/spreadsheets/{SHEET}/values/Log%21A%3AF:append").mock(
        return_value=httpx.Response(200, json={"updates": {"updatedRows": 1}})
    )
    resp = client.post(
        f"{VALUES}/Log!A:F:append",
        params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
        json={"values": [["date", "https://a.test", True, False, False, False]]},
        headers=auth(keys["uptime-monitor"]),
    )
    assert resp.status_code == 200
    assert (
        append.calls.last.request.content == b'{"values":[["date","https://a.test",true,false,false,false]]}'
    )

    put = respx.put(f"{PROXY}/v4/spreadsheets/{SHEET}/values/Sites%21B4").mock(
        return_value=httpx.Response(200, json={"updatedCells": 1})
    )
    resp = client.put(
        f"{VALUES}/Sites!B4",
        params={"valueInputOption": "RAW"},
        json={"values": [["DOWN"]]},
        headers=auth(keys["uptime-monitor"]),
    )
    assert resp.status_code == 200 and put.called


@respx.mock
def test_gmail_reads_for_the_medium_digest(relay):
    svc, client, keys = relay
    listed = respx.get(f"{PROXY}/gmail/v1/users/me/messages").mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "m1"}]})
    )
    resp = client.get(
        MESSAGES, params={"q": "Medium after:1", "maxResults": "20"}, headers=auth(keys["medium-digest"])
    )
    assert resp.json() == {"messages": [{"id": "m1"}]}
    assert listed.calls.last.request.headers["base-url-override"] == "https://gmail.googleapis.com"
    assert dict(listed.calls.last.request.url.params) == {"q": "Medium after:1", "maxResults": "20"}
    one = respx.get(f"{PROXY}/gmail/v1/users/me/messages/m1").mock(
        return_value=httpx.Response(200, json={"id": "m1", "payload": {}})
    )
    assert (
        client.get(
            f"{MESSAGES}/m1", params={"format": "full"}, headers=auth(keys["medium-digest"])
        ).status_code
        == 200
    )
    assert dict(one.calls.last.request.url.params) == {"format": "full"}


@respx.mock
def test_each_workflow_gets_only_its_own_calls(relay):
    svc, client, keys = relay
    proxy = respx.route(url__startswith=PROXY).mock(return_value=httpx.Response(200, json={}))
    uptime, medium = auth(keys["uptime-monitor"]), auth(keys["medium-digest"])
    assert client.get(MESSAGES, headers=uptime).status_code == 403  # the uptime monitor has no Gmail
    assert client.get(f"{VALUES}/Sites!A2:B", headers=medium).status_code == 403  # Medium has no Sheets
    other = f"/api/google-relay/sheets/v4/spreadsheets/{OTHER_SHEET}/values/Sites!A2:B"
    resp = client.get(other, headers=uptime)
    assert (
        resp.status_code == 403
        and "spreadsheet created for this deployment" in resp.json()["error"]["message"]
    )
    for method, path in (
        ("GET", f"/api/google-relay/sheets/v4/spreadsheets/{SHEET}"),  # whole spreadsheet
        ("POST", f"/api/google-relay/sheets/v4/spreadsheets/{SHEET}:batchUpdate"),
        ("POST", f"{VALUES}/Sites!A2:B:clear"),
        ("GET", f"{VALUES}/Sites!A2:B/../.."),
        ("GET", f"{VALUES}/'Other tab'!A1"),
        ("GET", "/api/google-relay/drive/v3/files"),
        ("PUT", f"{MESSAGES}/m1"),
        ("GET", f"{MESSAGES}/m1/attachments/a1"),
        ("GET", "/api/google-relay/gmail/v1/users/someone@else.test/messages"),
    ):
        resp = client.request(method, path, headers=uptime if "sheets" in path else medium, json={})
        assert resp.status_code == 404, (method, path)
    assert client.delete(f"{VALUES}/Sites!A2:B", headers=uptime).status_code in (404, 405)
    assert not proxy.called


@respx.mock
def test_keys_work_only_for_a_live_deployment(relay):
    svc, client, keys = relay
    proxy = respx.route(url__startswith=PROXY).mock(return_value=httpx.Response(200, json={}))
    path = f"{VALUES}/Sites!A2:B"
    uptime_key = keys["uptime-monitor"]
    dep_id, secret = uptime_key.split(".")
    for headers in (
        {},
        {"Authorization": uptime_key},  # no scheme
        {"Authorization": f"Basic {uptime_key}"},
        auth(f"{dep_id}.{secret[:-2]}xx"),  # wrong key
        auth(f"{int(dep_id) + 1}.{secret}"),  # the other deployment's id
        auth(f"999.{secret}"),
        auth("not-a-key"),
    ):
        resp = client.get(path, headers=headers)
        assert resp.status_code == 401, headers
        assert resp.json() == {"error": {"code": 401, "message": "Invalid Google relay key"}}

    update_deployment(svc, "uptime-monitor", status="failed")
    assert client.get(path, headers=auth(uptime_key)).status_code == 403
    update_deployment(svc, "uptime-monitor", status="active", expires_at=utcnow() - timedelta(seconds=1))
    assert client.get(path, headers=auth(uptime_key)).status_code == 403
    update_deployment(svc, "uptime-monitor", expires_at=utcnow() + timedelta(hours=1))
    assert client.get(path, headers=auth(uptime_key)).status_code == 200

    # A redeploy writes a new key's hash: the old key stops working.
    update_deployment(
        svc, "uptime-monitor", platform_refs={KEY_REF: new_key(int(dep_id))[1], "spreadsheet_id": SHEET}
    )
    assert client.get(path, headers=auth(uptime_key)).status_code == 401
    assert proxy.call_count == 1


@respx.mock
def test_google_connection_problems(relay):
    svc, client, keys = relay
    path, headers = f"{VALUES}/Sites!A2:B", auth(keys["uptime-monitor"])

    # Google's own errors pass through (the workflow's HTTP node shows them).
    respx.get(url__startswith=f"{PROXY}/v4/").mock(
        return_value=httpx.Response(
            403, json={"error": {"code": 403, "message": "The caller does not have permission"}}
        )
    )
    resp = client.get(path, headers=headers)
    assert (
        resp.status_code == 403 and resp.json()["error"]["message"] == "The caller does not have permission"
    )

    # Nango couldn't refresh the token (revoked, or Google's 7-day limit for Testing apps).
    refused = {
        "error": {"code": "server_error", "message": "Failed to get connection credentials: 'invalid_grant'"}
    }
    respx.get(url__startswith=f"{PROXY}/v4/").mock(return_value=httpx.Response(400, json=refused))
    resp = client.get(path, headers=headers)
    assert resp.status_code == 409 and "Reconnect it" in resp.json()["error"]["message"]

    respx.get(url__startswith=f"{PROXY}/v4/").mock(side_effect=httpx.ConnectError("down"))
    assert client.get(path, headers=headers).status_code == 502

    # The tester disconnected Google (or reconnected it with demo data).
    with svc.db.session() as db:
        db.query(Connection).one().method = "fake"
        db.commit()
    resp = client.get(path, headers=headers)
    assert resp.status_code == 409 and "reconnect it in the demo" in resp.json()["error"]["message"]


def test_request_bodies_are_checked(relay):
    svc, client, keys = relay
    headers = {**auth(keys["uptime-monitor"]), "Content-Type": "application/json"}
    resp = client.put(f"{VALUES}/Sites!B4", content=b"not json", headers=headers)
    assert resp.status_code == 400
    resp = client.put(f"{VALUES}/Sites!B4", content=b"[" + b"1," * 40_000 + b"1]", headers=headers)
    assert resp.status_code == 413


@respx.mock
def test_backend_google_calls_report_an_expired_connection():
    api = google.GoogleApi(NangoClient("nango-secret", NANGO, httpx.Client()), "g-1", "google")
    respx.get(url__startswith=PROXY).mock(
        return_value=httpx.Response(
            400, json={"error": {"code": "server_error", "message": "Failed to get connection"}}
        )
    )
    with pytest.raises(google.GoogleConnectionExpired):
        google.spreadsheet_url(api, SHEET)
    respx.get(url__startswith=PROXY).mock(
        return_value=httpx.Response(
            400, json={"error": {"code": "unknown_provider_config", "message": "no such"}}
        )
    )
    with pytest.raises(google.GoogleError, match="Nango error 400: no such"):
        google.spreadsheet_url(api, SHEET)
    assert google.user_email(api) is None
