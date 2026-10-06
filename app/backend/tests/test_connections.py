import base64

import httpx
import pytest
import respx

from workflow_demo.crypto import CryptoError, SecretBox
from workflow_demo.db import Connection

NANGO = "https://nango.test"
KEY = base64.b64encode(b"k" * 32).decode()


@pytest.fixture
def live(make_settings):
    """Services with Nango + encryption configured (fake platforms still on for deploys)."""
    from fastapi.testclient import TestClient

    from workflow_demo.app import build_services, create_app
    from workflow_demo.services.jobs import InlineJobRunner

    svc = build_services(
        make_settings(nango_secret_key="nango-secret", nango_host=NANGO, data_encryption_key=KEY),
        runner_factory=InlineJobRunner,
    )
    svc.db.create_all()
    with TestClient(create_app(svc.settings, svc)) as client:
        client.post("/api/auth/login", json={"username": "alice", "passcode": "pass"})
        yield svc, client


def nango_connection(connection_id, integration, username, raw=None, access_token="tok"):
    return {
        "id": 1,
        "connection_id": connection_id,
        "provider_config_key": integration,
        "provider": integration,
        "tags": {"end_user_id": username, "connector": integration},
        "credentials": {"type": "OAUTH2", "access_token": access_token, "raw": raw or {}},
    }


def test_secret_box_round_trip_and_binding():
    box = SecretBox(KEY)
    token = box.encrypt("m-AB-secret-value", "user:1:connector:meegle_mcp_token")
    assert "secret" not in token
    assert box.decrypt(token, "user:1:connector:meegle_mcp_token") == "m-AB-secret-value"
    with pytest.raises(CryptoError):
        box.decrypt(token, "user:2:connector:meegle_mcp_token")
    with pytest.raises(CryptoError):
        SecretBox(base64.b64encode(b"short").decode())
    for damaged in ("v1:abc", "v1:", "v1:" + base64.b64encode(b"x").decode(), "v2:" + token[3:]):
        with pytest.raises(CryptoError):
            box.decrypt(damaged, "user:1:connector:meegle_mcp_token")


@respx.mock
def test_slack_connect_flow(live):
    svc, client = live
    session = respx.post(f"{NANGO}/connect/sessions").mock(
        return_value=httpx.Response(
            201, json={"data": {"token": "sess-1", "expires_at": "2026-10-04T06:00:00Z"}}
        )
    )
    resp = client.post("/api/connections/slack/session")
    assert resp.status_code == 200
    assert resp.json() == {
        "token": "sess-1",
        "expires_at": "2026-10-04T06:00:00Z",
        "integration": "slack",
        "api_url": NANGO,
        "connect_url": "https://connect.nango.dev",
    }
    sent = session.calls.last.request
    assert sent.headers["authorization"] == "Bearer nango-secret"
    assert b'"end_user_id":"alice"' in sent.content and b'"allowed_integrations":["slack"]' in sent.content

    raw = {"team": {"id": "T1", "name": "Acme"}, "authed_user": {"id": "U42"}, "bot_user_id": "B1"}
    respx.get(f"{NANGO}/connections/conn-1").mock(
        return_value=httpx.Response(200, json=nango_connection("conn-1", "slack", "alice", raw))
    )
    out = client.post("/api/connections/slack/complete", json={"connection_id": "conn-1"}).json()
    assert out["method"] == "nango"
    assert out["details"] == {
        "label": "Slack · Acme",
        "team_id": "T1",
        "team_name": "Acme",
        "slack_user_id": "U42",
        "bot_user_id": "B1",
    }
    assert "tok" not in str(out)
    assert client.get("/api/workflows/meegle-daily-digest").json()["connectors"][1]["connected"] is True


@respx.mock
def test_connection_of_another_user_is_rejected(live):
    svc, client = live
    respx.get(f"{NANGO}/connections/conn-x").mock(
        return_value=httpx.Response(200, json=nango_connection("conn-x", "slack", "mallory"))
    )
    resp = client.post("/api/connections/slack/complete", json={"connection_id": "conn-x"})
    assert resp.status_code == 403
    assert client.get("/api/connections").json() == []


@respx.mock
def test_google_connect_reads_email_and_reconnect_replaces_old(live):
    svc, client = live
    userinfo = respx.get(f"{NANGO}/proxy/oauth2/v3/userinfo").mock(
        return_value=httpx.Response(200, json={"email": "alice@acme.dev"})
    )
    for cid in ("g-1", "g-2"):
        respx.get(f"{NANGO}/connections/{cid}").mock(
            return_value=httpx.Response(200, json=nango_connection(cid, "google", "alice"))
        )
    deleted = respx.delete(f"{NANGO}/connections/g-1").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    first = client.post("/api/connections/google/complete", json={"connection_id": "g-1"}).json()
    assert first["details"]["email"] == "alice@acme.dev"
    # Read through Nango's proxy as the new connection: the demo never handles a Google token.
    headers = userinfo.calls[0].request.headers
    assert (headers["connection-id"], headers["provider-config-key"]) == ("g-1", "google")
    assert headers["base-url-override"] == "https://www.googleapis.com"
    client.post("/api/connections/google/complete", json={"connection_id": "g-2"})
    assert deleted.called
    with svc.db.session() as db:
        assert db.query(Connection).one().nango_connection_id == "g-2"


@respx.mock
def test_reconnect_keeps_old_connection_if_saving_fails(live, monkeypatch):
    svc, client = live
    for cid in ("s-1", "s-2"):
        respx.get(f"{NANGO}/connections/{cid}").mock(
            return_value=httpx.Response(200, json=nango_connection(cid, "slack", "alice"))
        )
    deleted = respx.delete(url__regex=rf"{NANGO}/connections/.*").mock(return_value=httpx.Response(200))
    client.post("/api/connections/slack/complete", json={"connection_id": "s-1"})

    from sqlalchemy.orm import Session

    def broken_commit(self):
        raise RuntimeError("database went away")

    monkeypatch.setattr(Session, "commit", broken_commit)
    with pytest.raises(RuntimeError):
        client.post("/api/connections/slack/complete", json={"connection_id": "s-2"})
    monkeypatch.undo()
    assert not deleted.called
    with svc.db.session() as db:
        assert db.query(Connection).one().nango_connection_id == "s-1"


@respx.mock
def test_concurrent_first_connect_retries_as_update(live, monkeypatch):
    svc, client = live
    respx.get(f"{NANGO}/connections/s-2").mock(
        return_value=httpx.Response(200, json=nango_connection("s-2", "slack", "alice"))
    )
    deleted = respx.delete(f"{NANGO}/connections/s-1").mock(return_value=httpx.Response(200))
    from workflow_demo.services import connections as svc_connections

    real_get = svc_connections.get_connection
    calls = {"n": 0}

    def racing_get(db, user, connector_id):
        calls["n"] += 1
        if calls["n"] == 1:  # another request stores s-1 between our read and our insert
            with svc.db.session() as other:
                other.add(
                    Connection(
                        user_id=user.id,
                        connector=connector_id,
                        method="nango",
                        nango_integration="slack",
                        nango_connection_id="s-1",
                        details={},
                    )
                )
                other.commit()
            return None
        return real_get(db, user, connector_id)

    monkeypatch.setattr(svc_connections, "get_connection", racing_get)
    assert client.post("/api/connections/slack/complete", json={"connection_id": "s-2"}).status_code == 200
    assert deleted.called
    with svc.db.session() as db:
        assert db.query(Connection).one().nango_connection_id == "s-2"


@respx.mock
def test_connection_ids_are_validated_and_escaped(live):
    svc, client = live
    for bad in ("../connect/sessions", "..", "a/b", "x?y=1", ""):
        resp = client.post("/api/connections/slack/complete", json={"connection_id": bad})
        assert resp.status_code == 422, bad
    weird = respx.get(f"{NANGO}/connections/a%3Ab").mock(return_value=httpx.Response(200, json={"id": 1}))
    resp = client.post("/api/connections/slack/complete", json={"connection_id": "a:b"})
    assert weird.called
    assert resp.status_code == 502 and "unexpected" in resp.json()["detail"]


@respx.mock
def test_credentials_never_request_the_refresh_token(live):
    svc, client = live
    route = respx.get(f"{NANGO}/connections/conn-1").mock(
        return_value=httpx.Response(200, json=nango_connection("conn-1", "slack", "alice"))
    )
    client.post("/api/connections/slack/complete", json={"connection_id": "conn-1"})
    with svc.db.session() as db:
        from workflow_demo.services.connections import fresh_credentials

        assert fresh_credentials(svc, db.query(Connection).one()).access_token == "tok"
    for call in route.calls:
        assert "refresh_token" not in call.request.url.params


@respx.mock
def test_revoked_connection_asks_to_reconnect(live):
    # Google ends sign-ins to an External "Testing" OAuth app after 7 days; Nango then answers
    # with `invalid_credentials` (status taken from the refresh error, 400 for Google).
    svc, client = live
    respx.get(f"{NANGO}/proxy/oauth2/v3/userinfo").mock(
        return_value=httpx.Response(200, json={"email": "alice@acme.dev"})
    )
    route = respx.get(f"{NANGO}/connections/g-1").mock(
        return_value=httpx.Response(200, json=nango_connection("g-1", "google", "alice"))
    )
    client.post("/api/connections/google/complete", json={"connection_id": "g-1"})
    route.mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "code": "invalid_credentials",
                    "message": "The external API returned an error when trying to refresh the access "
                    "token. Please try again later.",
                }
            },
        )
    )
    from workflow_demo.services.connections import ConnectionError_, fresh_credentials

    with svc.db.session() as db, pytest.raises(ConnectionError_) as caught:
        fresh_credentials(svc, db.query(Connection).one())
    assert caught.value.status_code == 409
    assert caught.value.message == (
        "Your Google (Sheets and Gmail) connection has expired. Reconnect it, then try again."
    )


@respx.mock
def test_delete_removes_nango_connection(live):
    svc, client = live
    respx.get(f"{NANGO}/connections/conn-1").mock(
        return_value=httpx.Response(200, json=nango_connection("conn-1", "slack", "alice"))
    )
    client.post("/api/connections/slack/complete", json={"connection_id": "conn-1"})
    deleted = respx.delete(f"{NANGO}/connections/conn-1").mock(return_value=httpx.Response(404, json={}))
    assert client.delete("/api/connections/slack").status_code == 204
    assert deleted.called  # a 404 from Nango is fine
    assert client.get("/api/connections").json() == []


@respx.mock
def test_nango_errors_are_reported(live):
    svc, client = live
    respx.post(f"{NANGO}/connect/sessions").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad secret key"}})
    )
    resp = client.post("/api/connections/slack/session")
    assert resp.status_code == 502 and "bad secret key" in resp.json()["detail"]
    respx.post(f"{NANGO}/connect/sessions").mock(side_effect=httpx.ConnectTimeout("x"))
    assert "unreachable" in client.post("/api/connections/slack/session").json()["detail"]


def test_manual_secret_is_encrypted_and_never_returned(live):
    svc, client = live
    resp = client.put("/api/connections/meegle_mcp_token/secret", json={"value": "  m-AB-1234-abcd-wxyz  "})
    assert resp.status_code == 200
    body = resp.json()
    assert body["details"] == {"label": "saved · ends with wxyz"}
    assert "m-AB-1234" not in str(client.get("/api/connections").json())
    with svc.db.session() as db:
        record = db.query(Connection).one()
        assert "m-AB" not in record.secret_ciphertext
        from workflow_demo.services.connections import read_secret

        assert read_secret(svc, record.user, record) == "m-AB-1234-abcd-wxyz"

    wf = client.get("/api/workflows/meegle-daily-digest").json()
    token = next(c for c in wf["connectors"] if c["id"] == "meegle_mcp_token")
    assert token["connected"] and token["secret"] and token["label"] == "saved · ends with wxyz"
    assert "m-AB-1234" not in str(wf)


def test_manual_value_validation_and_plain_values(live):
    svc, client = live
    assert client.put("/api/connections/meegle_mcp_token/secret", json={"value": "short"}).status_code == 422
    assert (
        client.put("/api/connections/meegle_user_key/secret", json={"value": "bad key!"}).status_code == 422
    )
    out = client.put("/api/connections/meegle_user_key/secret", json={"value": "7123456789"}).json()
    assert out["details"] == {"label": "7123456789", "value": "7123456789"}
    assert client.put("/api/connections/slack/secret", json={"value": "xoxb-1"}).status_code == 400
    assert client.post("/api/connections/meegle_user_key/session").status_code == 400


def test_endpoints_report_missing_configuration(client, login):
    login()
    assert client.post("/api/connections/slack/session").status_code == 503
    resp = client.put("/api/connections/meegle_mcp_token/secret", json={"value": "m-AB-1234-abcd"})
    assert resp.status_code == 503
    assert client.get("/api/connections").json() == []


def test_empty_keys_leave_features_off(make_settings):
    from workflow_demo.app import build_services

    svc = build_services(make_settings(nango_secret_key="", data_encryption_key=""))
    assert svc.nango is None and svc.secret_box is None


@respx.mock
def test_slack_channels(live):
    svc, client = live
    assert client.get("/api/slack/channels").status_code == 409
    respx.get(f"{NANGO}/connections/conn-1").mock(
        return_value=httpx.Response(
            200, json=nango_connection("conn-1", "slack", "alice", access_token="xoxb-1")
        )
    )
    client.post("/api/connections/slack/complete", json={"connection_id": "conn-1"})
    pages = [
        httpx.Response(
            200,
            json={
                "ok": True,
                "channels": [{"id": "C2", "name": "zeta"}],
                "response_metadata": {"next_cursor": "n1"},
            },
        ),
        httpx.Response(
            200,
            json={
                "ok": True,
                "channels": [{"id": "C1", "name": "alpha"}],
                "response_metadata": {"next_cursor": ""},
            },
        ),
    ]
    slack = respx.get("https://slack.com/api/conversations.list").mock(side_effect=pages)
    assert client.get("/api/slack/channels").json() == [
        {"id": "C1", "name": "alpha"},
        {"id": "C2", "name": "zeta"},
    ]
    assert slack.calls[0].request.headers["authorization"] == "Bearer xoxb-1"

    respx.get("https://slack.com/api/conversations.list").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "missing_scope"})
    )
    resp = client.get("/api/slack/channels")
    assert resp.status_code == 502 and "missing_scope" in resp.json()["detail"]


def test_fake_slack_channels(client, login):
    login()
    client.post("/api/connections/slack/fake")
    assert [c["name"] for c in client.get("/api/slack/channels").json()] == ["general", "demo-alerts"]


def test_health_reports_connection_modes(live, client):
    svc, live_client = live
    assert live_client.get("/api/health").json()["nango_enabled"] is True
    assert client.get("/api/health").json()["nango_enabled"] is False


@respx.mock
def test_user_credentials_for_deploy_jobs(live):
    from workflow_demo.adapters.base import AdapterError
    from workflow_demo.db import User
    from workflow_demo.services.connections import UserCredentials

    svc, client = live
    route = respx.get(f"{NANGO}/connections/g-1").mock(
        return_value=httpx.Response(
            200,
            json={
                **nango_connection("g-1", "google", "alice", raw={"scope": "sheets"}),
                "credentials": {"access_token": "ya29", "refresh_token": "1//r", "raw": {"scope": "sheets"}},
            },
        )
    )
    respx.get(f"{NANGO}/proxy/oauth2/v3/userinfo").mock(return_value=httpx.Response(401))
    client.post("/api/connections/google/complete", json={"connection_id": "g-1"})
    client.put("/api/connections/meegle_mcp_token/secret", json={"value": "m-AB-1234-abcd"})
    client.post("/api/connections/slack/fake")  # fake mode is on in this fixture

    with svc.db.session() as db:
        creds = UserCredentials(svc, db.query(User).one())
        api = creds.google_api("google")  # Google calls go through Nango's proxy as this connection
        assert (api.connection_id, api.integration) == ("g-1", "google")
        tokens = creds.oauth_tokens("google")
        assert (tokens.access_token, tokens.scope) == ("ya29", "sheets")
        assert "refresh_token" not in route.calls.last.request.url.params
        with pytest.raises(AdapterError, match="demo data"):
            creds.google_api("slack")
        assert creds.secret_value("meegle_mcp_token") == "m-AB-1234-abcd"
        with pytest.raises(AdapterError, match="demo data"):
            creds.oauth_tokens("slack")
        with pytest.raises(AdapterError, match="Connect Meegle user key first"):
            creds.secret_value("meegle_user_key")
    client.post("/api/connections/meegle_user_key/fake")
    with svc.db.session() as db, pytest.raises(AdapterError, match="demo data"):
        UserCredentials(svc, db.query(User).one()).secret_value("meegle_user_key")
