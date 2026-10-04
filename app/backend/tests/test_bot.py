"""Shared Slack bot: "Activate for me", the bot API, and the real adapter's checks."""

import pytest

from workflow_demo.adapters.base import AdapterError, ConnectionInfo, DeployContext
from workflow_demo.adapters.modal import SharedBotAdapter
from workflow_demo.catalog.loader import load_catalog

BOT = {"Authorization": "Bearer bot-token"}
CATALOG = load_catalog()


@pytest.fixture
def bot_client(make_settings):
    from fastapi.testclient import TestClient

    from workflow_demo.app import build_services, create_app
    from workflow_demo.services.jobs import InlineJobRunner

    svc = build_services(make_settings(bot_api_token="bot-token"), runner_factory=InlineJobRunner)
    svc.db.create_all()
    with TestClient(create_app(svc.settings, svc)) as client:
        client.post("/api/auth/login", json={"username": "carol", "passcode": "pass"})
        client.post("/api/connections/slack/fake")  # slack_user_id UFAKE0001
        client.put("/api/connections/meegle_user_key/secret", json={"value": "carol_key"})
        yield client


def activate(client):
    assert client.post("/api/deployments/slack-meegle-bot", json={"settings": {}}).status_code == 202
    assert client.get("/api/workflows/slack-meegle-bot").json()["deployment"]["status"] == "active"


def test_bot_api_needs_the_token(bot_client):
    assert bot_client.get("/api/bot/user-map/UFAKE0001").status_code == 401
    assert (
        bot_client.get("/api/bot/user-map/UFAKE0001", headers={"Authorization": "Bearer nope"}).status_code
        == 401
    )
    assert (
        bot_client.get("/api/bot/user-map/UFAKE0001", headers={"Authorization": "bot-token"}).status_code
        == 401
    )


def test_bot_api_is_off_without_a_token(client):
    assert client.get("/api/bot/user-map/U1", headers=BOT).status_code == 503


def test_activation_maps_the_user_and_records_cards(bot_client):
    assert bot_client.get("/api/bot/user-map/UFAKE0001", headers=BOT).status_code == 404
    activate(bot_client)
    assert bot_client.get("/api/bot/user-map/UFAKE0001", headers=BOT).json() == {"user_key": "carol_key"}
    assert bot_client.get("/api/bot/user-map/UOTHER01", headers=BOT).status_code == 404

    card = {"slack_user_id": "UFAKE0001", "title": "Fix login", "url": "https://meegle.com/space/story/1"}
    assert bot_client.post("/api/bot/cards", json=card, headers=BOT).json() == {"recorded": True}
    runs = bot_client.get("/api/deployments/slack-meegle-bot/runs").json()
    assert runs[0]["summary"] == "Created card “Fix login” — https://meegle.com/space/story/1"
    timeline = bot_client.get("/api/workflows/slack-meegle-bot").json()["deployment"]["events"]
    assert any(e["type"] == "card_created" for e in timeline)

    # Redeploy (e.g. after changing the user key) keeps the card history.
    bot_client.put("/api/connections/meegle_user_key/secret", json={"value": "carol_key2"})
    activate(bot_client)
    assert bot_client.get("/api/bot/user-map/UFAKE0001", headers=BOT).json() == {"user_key": "carol_key2"}
    assert len(bot_client.get("/api/deployments/slack-meegle-bot/runs").json()) == 1

    # Deactivating ends the mapping; later cards aren't recorded.
    assert bot_client.delete("/api/deployments/slack-meegle-bot").status_code == 202
    assert bot_client.get("/api/bot/user-map/UFAKE0001", headers=BOT).status_code == 404
    assert bot_client.post("/api/bot/cards", json=card, headers=BOT).json() == {"recorded": False}


@pytest.mark.parametrize(
    "card",
    [
        {"slack_user_id": "UFAKE0001", "title": "x", "url": "http://insecure"},
        {"slack_user_id": "not-a-user", "title": "x", "url": "https://ok"},
        {"slack_user_id": "UFAKE0001", "title": "", "url": "https://ok"},
    ],
)
def test_card_validation(bot_client, card):
    assert bot_client.post("/api/bot/cards", json=card, headers=BOT).status_code == 422


# --------------------------------------------------------------------------- real adapter


class Secrets:
    def oauth_tokens(self, connector, *, with_refresh_token=False):
        raise AssertionError("the bot adapter never needs OAuth tokens")

    def secret_value(self, connector):
        assert connector == "meegle_user_key"
        return "dave_key"


def bot_context(slack=None, previous_refs=None):
    slack = slack or ConnectionInfo(
        connector="slack", method="nango", details={"slack_user_id": "U42", "team_id": "T1"}
    )
    return DeployContext(
        username="dave",
        workflow=CATALOG.workflow("slack-meegle-bot"),
        deployment_id=3,
        settings={},
        connections={"slack": slack},
        refs={},
        credentials=Secrets(),
        previous_refs=previous_refs or {},
    )


def test_shared_bot_adapter(make_settings):
    adapter = SharedBotAdapter(make_settings(bot_api_token="t", slack_bot_team_id="T1"))
    assert adapter.check_available(CATALOG.workflow("slack-meegle-bot")).available
    result = adapter.deploy(bot_context(previous_refs={"runs": [{"id": "card-1"}]}))
    assert result.refs == {"slack_user_id": "U42", "meegle_user_key": "dave_key", "runs": [{"id": "card-1"}]}
    with pytest.raises(AdapterError, match="mention"):
        adapter.run_now(bot_context())

    fake = ConnectionInfo(connector="slack", method="fake", details={"slack_user_id": "UFAKE0001"})
    with pytest.raises(AdapterError, match="demo data"):
        adapter.deploy(bot_context(fake))
    no_id = ConnectionInfo(connector="slack", method="nango", details={"team_id": "T1"})
    with pytest.raises(AdapterError, match="user ID"):
        adapter.deploy(bot_context(no_id))
    other_team = ConnectionInfo(
        connector="slack", method="nango", details={"slack_user_id": "U4", "team_id": "T9"}
    )
    with pytest.raises(AdapterError, match="workspace the bot is in"):
        adapter.deploy(bot_context(other_team))


def test_shared_bot_adapter_needs_the_token(make_settings):
    adapter = SharedBotAdapter(make_settings())
    availability = adapter.check_available(CATALOG.workflow("slack-meegle-bot"))
    assert not availability.available and "BOT_API_TOKEN" in availability.reason
    with pytest.raises(AdapterError, match="BOT_API_TOKEN"):
        adapter.deploy(bot_context())


def test_mapping_follows_expiry_and_connections(bot_client):
    from datetime import timedelta

    from workflow_demo.db import Deployment, utcnow

    activate(bot_client)
    # A corrected user key applies without activating again.
    bot_client.put("/api/connections/meegle_user_key/secret", json={"value": "carol_new"})
    assert bot_client.get("/api/bot/user-map/UFAKE0001", headers=BOT).json() == {"user_key": "carol_new"}
    # Disconnecting Slack (or Meegle) ends the mapping at once.
    bot_client.delete("/api/connections/slack")
    assert bot_client.get("/api/bot/user-map/UFAKE0001", headers=BOT).status_code == 404
    bot_client.post("/api/connections/slack/fake")
    assert bot_client.get("/api/bot/user-map/UFAKE0001", headers=BOT).status_code == 200
    bot_client.delete("/api/connections/meegle_user_key")
    assert bot_client.get("/api/bot/user-map/UFAKE0001", headers=BOT).status_code == 404
    bot_client.put("/api/connections/meegle_user_key/secret", json={"value": "carol_key"})

    # Past its expiry time, even before the sweeper runs.
    svc = bot_client.app.state.services
    with svc.db.session() as db:
        db.query(Deployment).one().expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert bot_client.get("/api/bot/user-map/UFAKE0001", headers=BOT).status_code == 404
    card = {"slack_user_id": "UFAKE0001", "title": "Late", "url": "https://meegle.com/x/2"}
    assert bot_client.post("/api/bot/cards", json=card, headers=BOT).json() == {"recorded": False}


def test_long_titles_are_shortened(bot_client):
    activate(bot_client)
    card = {"slack_user_id": "UFAKE0001", "title": "x" * 1000, "url": "https://meegle.com/x/3"}
    assert bot_client.post("/api/bot/cards", json=card, headers=BOT).json() == {"recorded": True}
    summary = bot_client.get("/api/deployments/slack-meegle-bot/runs").json()[0]["summary"]
    assert "x" * 199 + "…”" in summary and "x" * 200 not in summary
