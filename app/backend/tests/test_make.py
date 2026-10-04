"""Make Bridge client and adapter against a mocked Bridge portal API (respx)."""

import base64
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from workflow_demo.adapters import make as make_module
from workflow_demo.adapters.base import AdapterError, DeployContext
from workflow_demo.adapters.make import MakeBridgeAdapter, summarize_log
from workflow_demo.catalog.loader import load_catalog
from workflow_demo.make_bridge import sign_jwt

BRIDGE = "https://us2.make.com/portal/api/bridge"
CATALOG = load_catalog()
CALLBACK = "http://testserver/make/callback?state=signed-state"
NAME = "[demo] GitHub merge → Slack · alice"


def b64decode(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def jwt_parts(token):
    header, claims, signature = token.split(".")
    return json.loads(b64decode(header)), json.loads(b64decode(claims)), signature


@pytest.fixture
def adapter(make_settings, monkeypatch):
    monkeypatch.setattr(make_module.time, "sleep", lambda seconds: None)
    settings = make_settings(
        make_bridge_key_id="key-1",
        make_bridge_secret="bridge-secret",
        make_bridge_template_id=42,
        make_team_id=7,
    )
    return MakeBridgeAdapter(settings, httpx.Client())


def context(refs=None):
    return DeployContext(
        username="alice",
        workflow=CATALOG.workflow("github-merge-slack"),
        deployment_id=5,
        settings={},
        connections={},
        refs=refs or {},
        user_step_state="signed-state",
        callback_url=CALLBACK,
    )


def test_jwt_is_hs256_with_key_id_and_short_expiry():
    token = sign_jwt("workflow-demo:alice", "key-1", "bridge-secret", now=1_000)
    header, claims, signature = jwt_parts(token)
    assert header == {"alg": "HS256", "typ": "JWT", "kid": "key-1"}
    assert claims["sub"] == "workflow-demo:alice" and claims["exp"] - claims["iat"] == 120 and claims["jti"]
    signing_input = token.rsplit(".", 1)[0].encode()
    expected = hmac.new(b"bridge-secret", signing_input, hashlib.sha256).digest()
    assert b64decode(signature) == expected
    assert jwt_parts(sign_jwt("s", "k", "x"))[1]["jti"] != jwt_parts(sign_jwt("s", "k", "x"))[1]["jti"]


def test_unconfigured(make_settings):
    adapter = MakeBridgeAdapter(make_settings(), httpx.Client())
    availability = adapter.check_available()
    assert not availability.available
    assert "MAKE_BRIDGE_KEY_ID" in availability.reason and "MAKE_BRIDGE_TEMPLATE_ID" in availability.reason
    with pytest.raises(AdapterError, match="Not set up"):
        adapter.deploy(context())


@respx.mock
def test_availability_is_checked_and_cached(adapter):
    route = respx.get(f"{BRIDGE}/integrations/").mock(
        return_value=httpx.Response(200, json={"integrations": []})
    )
    assert adapter.check_available().available
    assert adapter.check_available().available
    assert route.call_count == 1
    request = route.calls.last.request
    assert request.url.params["teamId"] == "7"
    assert (
        jwt_parts(request.headers["authorization"].removeprefix("Bearer "))[1]["sub"]
        == "workflow-demo:setup-check"
    )


@respx.mock
@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(403, json={"message": "Bridge is not enabled"}), "Deploy unavailable"),
        (httpx.Response(502, text="bad gateway"), "unreachable"),
    ],
)
def test_unavailable_bridge(adapter, response, reason):
    respx.get(f"{BRIDGE}/integrations/").mock(return_value=response)
    availability = adapter.check_available()
    assert not availability.available and reason in availability.reason


@respx.mock
def test_deploy_starts_the_popup_flow(adapter):
    route = respx.post(f"{BRIDGE}/integrations/init/42").mock(
        return_value=httpx.Response(
            200, json={"publicUrl": "https://us2.make.com/portal/flow/abc", "flow": {"id": "f-1"}}
        )
    )
    result = adapter.deploy(context())
    body = json.loads(route.calls.last.request.content)
    assert body["redirectUri"] == CALLBACK
    assert body["allowReusingComponents"] is True and body["autoActivate"] is False
    assert body["scenario"] == {"name": "[demo] GitHub merge → Slack · alice", "enable": False}
    token = route.calls.last.request.headers["authorization"].removeprefix("Bearer ")
    assert jwt_parts(token)[1]["sub"] == "workflow-demo:alice"
    assert result.status == "awaiting_user"
    assert result.refs == {"popup_url": "https://us2.make.com/portal/flow/abc", "flow_id": "f-1"}


def flow(completed=True, scenarios=(101,), message="done"):
    return {
        "flow": {
            "id": "f-1",
            "statusId": 3 if completed else 1,
            "statusMessage": message,
            "isCompleted": completed,
            "result": {"scenarios": [{"id": s, "description": "x"} for s in scenarios]}
            if completed
            else None,
        }
    }


@respx.mock
def test_finish_waits_for_make_then_activates(adapter):
    check = respx.get(f"{BRIDGE}/integrations/check-init/f-1").mock(
        side_effect=[
            httpx.Response(200, json=flow(False)),
            httpx.Response(200, json=flow(scenarios=(101, 102))),
        ]
    )
    activated = respx.post(f"{BRIDGE}/integrations/101/activate").mock(
        return_value=httpx.Response(200, json={"integration": {"scenarioId": 101}})
    )
    stray = respx.delete(f"{BRIDGE}/integrations/102").mock(return_value=httpx.Response(200, json={}))
    # A scenario left by an abandoned earlier popup (same name) is removed; others are kept.
    respx.get(f"{BRIDGE}/integrations/").mock(
        return_value=httpx.Response(
            200,
            json={
                "integrations": [
                    {"scenario": {"id": 101, "name": NAME}},
                    {"scenario": {"id": 90, "name": NAME}},
                    {"scenario": {"id": 91, "name": "[demo] Something else · alice"}},
                ]
            },
        )
    )
    old_popup = respx.delete(f"{BRIDGE}/integrations/90").mock(return_value=httpx.Response(200, json={}))
    kept = respx.delete(f"{BRIDGE}/integrations/91")
    result = adapter.finish_user_step(context({"popup_url": "u", "flow_id": "f-1"}), {})
    assert check.call_count == 2 and activated.called and stray.called
    assert old_popup.called and not kept.called
    assert result.status == "active" and result.refs == {"flow_id": "f-1", "scenario_id": 101}


@respx.mock
def test_finish_errors(adapter):
    respx.get(f"{BRIDGE}/integrations/check-init/f-1").mock(
        return_value=httpx.Response(200, json=flow(False, message="waiting for connections"))
    )
    with pytest.raises(AdapterError, match="waiting for connections"):
        adapter.finish_user_step(context({"flow_id": "f-1"}), {})

    respx.get(f"{BRIDGE}/integrations/check-init/f-1").mock(
        return_value=httpx.Response(200, json=flow(scenarios=()))
    )
    with pytest.raises(AdapterError, match="without creating a scenario"):
        adapter.finish_user_step(context({"flow_id": "f-1"}), {})

    respx.get(f"{BRIDGE}/integrations/check-init/f-1").mock(return_value=httpx.Response(200, json=flow()))
    respx.post(f"{BRIDGE}/integrations/101/activate").mock(
        return_value=httpx.Response(400, json={"message": "nope"})
    )
    cleaned = respx.delete(f"{BRIDGE}/integrations/101").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AdapterError, match="nope"):
        adapter.finish_user_step(context({"flow_id": "f-1"}), {})
    assert cleaned.called

    with pytest.raises(AdapterError, match="no Make setup"):
        adapter.finish_user_step(context({}), {})


@respx.mock
def test_undeploy(adapter):
    respx.get(f"{BRIDGE}/integrations/").mock(return_value=httpx.Response(200, json={"integrations": []}))
    deactivated = respx.post(f"{BRIDGE}/integrations/101/deactivate").mock(
        return_value=httpx.Response(200, json={})
    )
    deleted = respx.delete(f"{BRIDGE}/integrations/101").mock(return_value=httpx.Response(404, json={}))
    adapter.undeploy(context({"scenario_id": 101, "flow_id": "f-1"}))
    assert deactivated.called and deleted.called

    # The popup was finished but the callback never arrived: clean up what Make created.
    respx.get(f"{BRIDGE}/integrations/check-init/f-2").mock(
        return_value=httpx.Response(200, json=flow(scenarios=(103,)))
    )
    respx.post(f"{BRIDGE}/integrations/103/deactivate").mock(return_value=httpx.Response(200, json={}))
    orphan = respx.delete(f"{BRIDGE}/integrations/103").mock(return_value=httpx.Response(200, json={}))
    adapter.undeploy(context({"popup_url": "u", "flow_id": "f-2"}))
    assert orphan.called

    respx.delete(f"{BRIDGE}/integrations/101").mock(
        return_value=httpx.Response(500, json={"message": "down"})
    )
    with pytest.raises(AdapterError, match="down"):
        adapter.undeploy(context({"scenario_id": 101}))


@respx.mock
def test_run_now_and_runs(adapter):
    respx.post(f"{BRIDGE}/integrations/101/run").mock(
        return_value=httpx.Response(200, json={"executionId": "ex-1", "statusUrl": "https://x"})
    )
    started = adapter.run_now(context({"scenario_id": 101}))
    assert started.run_id == "ex-1"
    with pytest.raises(AdapterError, match="no Make scenario"):
        adapter.run_now(context({}))

    respx.get(f"{BRIDGE}/scenarios/101/logs").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "ex-2",
                    "status": 3,
                    "timestamp": "2026-10-04T06:00:00.000Z",
                    "duration": 1500,
                    "operations": 2,
                    "error": {"message": "GitHub: Not Found"},
                },
                {
                    "id": "ex-1",
                    "status": 1,
                    "timestamp": "2026-10-04T05:50:00.000Z",
                    "duration": 800,
                    "operations": 3,
                },
                {"eventType": "MODIFY", "timestamp": "2026-10-04T05:40:00.000Z"},
                {"id": "ex-0", "status": 2, "timestamp": "2026-10-04T05:30:00.000Z", "operations": 1},
            ],
        )
    )
    runs = adapter.recent_runs(context({"scenario_id": 101}))
    assert [r.id for r in runs] == ["ex-2", "ex-1", "ex-0"]
    assert runs[0].status == "error" and runs[0].error == "GitHub: Not Found"
    assert runs[0].finished_at.second == 1 and runs[0].finished_at.microsecond == 500000
    assert runs[1].status == "success" and runs[1].summary == "3 operations"
    assert runs[2].summary == "1 operation (with warnings)"
    assert adapter.recent_runs(context({})) == []


def test_summarize_log_tolerates_odd_items():
    run = summarize_log({"status": 3})
    assert (
        run.status == "error"
        and run.error == "The run failed; see Make for details"
        and run.started_at is None
    )


@pytest.fixture
def real(make_settings, monkeypatch):
    from fastapi.testclient import TestClient

    from workflow_demo.app import build_services, create_app
    from workflow_demo.services.jobs import InlineJobRunner

    monkeypatch.setattr(make_module.time, "sleep", lambda seconds: None)
    settings = make_settings(
        DEMO_FAKE_PLATFORMS=False,
        make_bridge_key_id="key-1",
        make_bridge_secret="bridge-secret",
        make_bridge_template_id=42,
    )
    svc = build_services(settings, runner_factory=InlineJobRunner)
    svc.db.create_all()
    with TestClient(create_app(settings, svc)) as client:
        client.post("/api/auth/login", json={"username": "bob", "passcode": "pass"})
        yield client


@respx.mock
def test_popup_flow_through_the_api(real):
    client = real
    respx.get(f"{BRIDGE}/integrations/").mock(return_value=httpx.Response(200, json={"integrations": []}))
    init = respx.post(f"{BRIDGE}/integrations/init/42").mock(
        return_value=httpx.Response(
            200, json={"publicUrl": "https://us2.make.com/portal/flow/xyz", "flow": {"id": "f-9"}}
        )
    )
    assert client.post("/api/deployments/github-merge-slack", json={"settings": {}}).status_code == 202
    dep = client.get("/api/workflows/github-merge-slack").json()["deployment"]
    assert dep["status"] == "awaiting_user" and dep["popup_url"] == "https://us2.make.com/portal/flow/xyz"

    # Make sends the popup back to the redirect URI it was given (plus its own parameters).
    redirect = json.loads(init.calls.last.request.content)["redirectUri"]
    state = parse_qs(urlparse(redirect).query)["state"][0]
    respx.get(f"{BRIDGE}/integrations/check-init/f-9").mock(
        return_value=httpx.Response(200, json=flow(scenarios=(555,)))
    )
    respx.post(f"{BRIDGE}/integrations/555/activate").mock(
        return_value=httpx.Response(200, json={"integration": {"scenarioId": 555}})
    )
    page = client.get("/make/callback", params={"state": state, "flowId": "f-9"})
    assert page.status_code == 200 and "Almost done" in page.text
    dep = client.get("/api/workflows/github-merge-slack").json()["deployment"]
    assert dep["status"] == "active" and dep["popup_url"] is None

    respx.post(f"{BRIDGE}/integrations/555/deactivate").mock(return_value=httpx.Response(200, json={}))
    deleted = respx.delete(f"{BRIDGE}/integrations/555").mock(return_value=httpx.Response(200, json={}))
    assert client.delete("/api/deployments/github-merge-slack").status_code == 202
    assert deleted.called


@respx.mock
def test_finish_retries_transient_errors(adapter):
    respx.get(f"{BRIDGE}/integrations/check-init/f-1").mock(
        side_effect=[httpx.Response(502, text="bad gateway"), httpx.Response(200, json=flow())]
    )
    respx.post(f"{BRIDGE}/integrations/101/activate").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{BRIDGE}/integrations/").mock(return_value=httpx.Response(200, json={"integrations": []}))
    assert adapter.finish_user_step(context({"flow_id": "f-1"}), {}).refs["scenario_id"] == 101

    respx.get(f"{BRIDGE}/integrations/check-init/f-1").mock(
        return_value=httpx.Response(400, json={"message": "bad flow"})
    )
    with pytest.raises(AdapterError, match="bad flow"):
        adapter.finish_user_step(context({"flow_id": "f-1"}), {})


@respx.mock
def test_rejected_key_is_reported_and_rechecked_soon(adapter):
    respx.get(f"{BRIDGE}/integrations/").mock(
        return_value=httpx.Response(401, json={"message": "invalid token"})
    )
    availability = adapter.check_available()
    assert "MAKE_BRIDGE_SECRET" in availability.reason
    assert adapter._availability[0] - make_module.time.monotonic() <= make_module.RETRY_TTL


def test_empty_env_values_count_as_unset(make_settings, monkeypatch):
    monkeypatch.setenv("MAKE_BRIDGE_TEMPLATE_ID", "")
    monkeypatch.setenv("MAKE_TEAM_ID", "")
    settings = make_settings()
    assert settings.make_bridge_template_id is None and settings.make_team_id is None


@respx.mock
def test_only_finished_executions_are_runs(adapter):
    respx.get(f"{BRIDGE}/scenarios/101/logs").mock(
        return_value=httpx.Response(
            200,
            json={
                "scenarioLogs": [
                    {"id": "ex-1", "eventType": "EXECUTION_START", "timestamp": "2026-10-04T06:00:00Z"},
                    {
                        "id": "ex-1",
                        "eventType": "EXECUTION_END",
                        "status": 1,
                        "timestamp": "2026-10-04T06:00:00Z",
                    },
                ]
            },
        )
    )
    runs = adapter.recent_runs(context({"scenario_id": 101}))
    assert [(r.id, r.status) for r in runs] == [("ex-1", "success")]
