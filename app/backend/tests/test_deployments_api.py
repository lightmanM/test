from urllib.parse import parse_qs, urlparse

import pytest

UPTIME_SETTINGS = {"slack_channel": "C0123ABCD"}


@pytest.fixture
def user(client, login):
    login("alice")
    return client


def connect(client, *connectors):
    for connector in connectors:
        assert client.post(f"/api/connections/{connector}/fake").status_code == 200


def test_catalog_lists_workflows_with_readiness(user):
    workflows = user.get("/api/workflows").json()
    assert [w["id"] for w in workflows] == [
        "uptime-monitor",
        "meegle-daily-digest",
        "medium-digest",
        "github-merge-slack",
        "slack-meegle-bot",
    ]
    by_id = {w["id"]: w for w in workflows}
    assert by_id["uptime-monitor"]["ready"] is False
    assert by_id["github-merge-slack"]["ready"] is True  # its accounts are connected in Make's popup
    assert all(c["managed_by_platform"] for c in by_id["github-merge-slack"]["connectors"])
    assert all(w["available"] for w in workflows)

    connect(user, "google", "slack")
    uptime = user.get("/api/workflows/uptime-monitor").json()
    assert uptime["ready"] is True
    assert [s["key"] for s in uptime["settings"]] == ["slack_channel", "sites"]
    assert uptime["run_now"] is True
    assert user.get("/api/workflows/slack-meegle-bot").json()["shared_deployment"] is True
    assert user.get("/api/workflows/nope").status_code == 404


def test_deploy_requires_connections_and_valid_settings(user):
    resp = user.post("/api/deployments/uptime-monitor", json={"settings": UPTIME_SETTINGS})
    assert resp.status_code == 409
    assert "Connect first" in resp.json()["detail"]

    connect(user, "google", "slack")
    resp = user.post("/api/deployments/uptime-monitor", json={"settings": {"slack_channel": "general"}})
    assert resp.status_code == 422
    assert "slack_channel" in resp.json()["detail"]["fields"]


def test_deploy_run_redeploy_delete(user):
    connect(user, "google", "slack")
    resp = user.post("/api/deployments/uptime-monitor", json={"settings": UPTIME_SETTINGS})
    assert resp.status_code == 202
    dep = user.get("/api/deployments/uptime-monitor").json()
    assert dep["status"] == "active"
    assert dep["settings"]["sites"] == ["https://example.com", "https://httpbin.org/status/503"]
    assert dep["expires_at"] is not None
    assert [e["type"] for e in dep["events"]] == ["requested", "active"]

    assert user.get("/api/deployments/uptime-monitor/runs").json() == []
    started = user.post("/api/deployments/uptime-monitor/run").json()
    assert started["run_id"] == "run-1"
    runs = user.get("/api/deployments/uptime-monitor/runs").json()
    assert runs[0]["status"] == "success" and "DOWN" in runs[0]["summary"]

    user.post(
        "/api/deployments/uptime-monitor", json={"settings": {**UPTIME_SETTINGS, "sites": ["https://a.dev"]}}
    )
    dep = user.get("/api/deployments/uptime-monitor").json()
    assert dep["status"] == "active"
    assert dep["settings"]["sites"] == ["https://a.dev"]
    assert [e["type"] for e in dep["events"]][-3:] == ["requested", "removed", "active"]

    assert user.delete("/api/deployments/uptime-monitor").status_code == 202
    dep = user.get("/api/deployments/uptime-monitor").json()
    assert dep["status"] == "stopped"
    assert dep["expires_at"] is None
    assert user.post("/api/deployments/uptime-monitor/run").status_code == 409

    # deploy again after delete
    user.post("/api/deployments/uptime-monitor", json={"settings": UPTIME_SETTINGS})
    assert user.get("/api/deployments/uptime-monitor").json()["status"] == "active"


def test_bot_has_no_run_now(user):
    connect(user, "slack", "meegle_user_key")
    user.post("/api/deployments/slack-meegle-bot", json={"settings": {}})
    assert user.post("/api/deployments/slack-meegle-bot/run").status_code == 400


def test_make_popup_flow(user):
    resp = user.post("/api/deployments/github-merge-slack", json={"settings": {}})
    dep = resp.json()
    assert dep["status"] == "awaiting_user"
    popup = urlparse(dep["popup_url"])
    assert popup.path == "/fake/make-popup"
    state = parse_qs(popup.query)["state"][0]

    assert user.get(f"/fake/make-popup?state={state}").status_code == 200
    assert user.get("/make/callback?state=forged").status_code == 400
    page = user.get(f"/make/callback?state={state}")
    assert page.status_code == 200 and "Almost done" in page.text
    dep = user.get("/api/deployments/github-merge-slack").json()
    assert dep["status"] == "active"
    assert dep["popup_url"] is None
    # the link can't be replayed once the step is done
    assert user.get(f"/make/callback?state={state}").status_code == 400


def test_failed_deploy_is_reported_and_can_be_retried(user, services):
    from workflow_demo.adapters.base import AdapterError
    from workflow_demo.catalog.models import Platform

    adapter = services.registry.get(Platform.N8N)
    original = adapter.deploy

    def broken(ctx):
        raise AdapterError("n8n is unreachable")

    adapter.deploy = broken
    connect(user, "google", "slack")
    user.post("/api/deployments/uptime-monitor", json={"settings": UPTIME_SETTINGS})
    dep = user.get("/api/deployments/uptime-monitor").json()
    assert dep["status"] == "failed"
    assert dep["error"] == "n8n is unreachable"

    adapter.deploy = original
    user.post("/api/deployments/uptime-monitor", json={"settings": UPTIME_SETTINGS})
    assert user.get("/api/deployments/uptime-monitor").json()["status"] == "active"


def test_busy_deployment_rejects_new_requests(user, services):
    from workflow_demo.db import Deployment

    connect(user, "google", "slack")
    user.post("/api/deployments/uptime-monitor", json={"settings": UPTIME_SETTINGS})
    with services.db.session() as db:
        dep = db.query(Deployment).one()
        dep.status = "deploying"
        db.commit()
    assert user.post("/api/deployments/uptime-monitor", json={"settings": UPTIME_SETTINGS}).status_code == 409
    assert user.delete("/api/deployments/uptime-monitor").status_code == 409


def test_unavailable_platform_blocks_deploy(user, services):
    from workflow_demo.adapters.base import Availability
    from workflow_demo.catalog.models import Platform

    services.registry.get(Platform.MAKE).check_available = lambda entry=None: Availability(
        False, "Make Bridge is not enabled"
    )
    workflows = {w["id"]: w for w in user.get("/api/workflows").json()}
    assert workflows["github-merge-slack"]["available"] is False
    assert workflows["github-merge-slack"]["unavailable_reason"] == "Make Bridge is not enabled"
    resp = user.post("/api/deployments/github-merge-slack", json={"settings": {}})
    assert resp.status_code == 409


def test_users_only_see_their_own_deployments(client, login):
    login("alice")
    connect(client, "google", "slack")
    client.post("/api/deployments/uptime-monitor", json={"settings": UPTIME_SETTINGS})
    login("bob")
    assert client.get("/api/deployments/uptime-monitor").status_code == 404
    assert all(w["deployment"] is None for w in client.get("/api/workflows").json())


def test_connections_list_and_delete(user):
    connect(user, "slack")
    assert [c["connector"] for c in user.get("/api/connections").json()] == ["slack"]
    assert user.delete("/api/connections/slack").status_code == 204
    assert user.get("/api/connections").json() == []
    assert user.post("/api/connections/make_github/fake").status_code == 400
    assert user.post("/api/connections/nope/fake").status_code == 404


def test_fake_connect_disabled_outside_fake_mode(user, services):
    services.settings.fake_platforms = False
    assert user.post("/api/connections/slack/fake").status_code == 404
