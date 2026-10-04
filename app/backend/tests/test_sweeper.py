"""The sweeper: 24 h limit, abandoned popups, lost jobs, platform orphans."""

from datetime import timedelta

import httpx
import pytest
import respx

from workflow_demo.adapters.base import DeploymentSnapshot
from workflow_demo.adapters.make import MakeBridgeAdapter
from workflow_demo.adapters.n8n import N8nAdapter
from workflow_demo.catalog.loader import load_catalog
from workflow_demo.db import Deployment, Job, utcnow
from workflow_demo.n8n.client import N8nClient
from workflow_demo.services.sweeper import ABANDONED_POPUP, Sweeper, sweep

UPTIME = {"slack_channel": "C0123ABCD"}
CATALOG = load_catalog()


@pytest.fixture
def user(client, login):
    login()
    for connector in ("google", "slack"):
        client.post(f"/api/connections/{connector}/fake")
    return client


def deployments(services):
    with services.db.session() as db:
        return {d.workflow_id: d for d in db.query(Deployment).all()}


def shift(services, workflow_id, **changes):
    with services.db.session() as db:
        dep = db.query(Deployment).filter_by(workflow_id=workflow_id).one()
        for key, value in changes.items():
            setattr(dep, key, value)
        db.commit()


def test_expired_and_abandoned_deployments_are_stopped(user, services):
    user.post("/api/deployments/uptime-monitor", json={"settings": UPTIME})
    user.post("/api/deployments/github-merge-slack", json={"settings": {}})  # waits for the popup
    assert {k: d.status for k, d in deployments(services).items()} == {
        "uptime-monitor": "active",
        "github-merge-slack": "awaiting_user",
    }
    assert sweep(services).stopped == []  # nothing is due yet

    shift(services, "uptime-monitor", expires_at=utcnow() - timedelta(seconds=1))
    shift(services, "github-merge-slack", updated_at=utcnow() - ABANDONED_POPUP - timedelta(minutes=1))
    report = sweep(services)
    assert sorted(report.stopped) == [
        "alice / github-merge-slack: The platform popup wasn't finished within an hour",
        "alice / uptime-monitor: The demo time limit was reached",
    ]
    deps = deployments(services)
    assert deps["uptime-monitor"].status == "stopped" and deps["uptime-monitor"].expires_at is None
    assert deps["github-merge-slack"].status == "stopped"
    timeline = user.get("/api/workflows/uptime-monitor").json()["deployment"]["events"]
    assert timeline[-1]["message"] == "Stopped automatically after the demo time limit"
    popup = user.get("/api/workflows/github-merge-slack").json()["deployment"]["events"]
    assert popup[-1]["message"] == "Stopped because the platform popup wasn't finished"
    assert sweep(services).stopped == []


def test_failed_cleanup_isnt_retried_every_sweep(user, services):
    from workflow_demo.adapters.base import AdapterError
    from workflow_demo.catalog.models import Platform

    user.post("/api/deployments/uptime-monitor", json={"settings": UPTIME})
    shift(services, "uptime-monitor", expires_at=utcnow() - timedelta(seconds=1))

    def broken(ctx):
        raise AdapterError("n8n is down")

    services.registry.get(Platform.N8N).undeploy = broken
    assert len(sweep(services).stopped) == 1
    dep = deployments(services)["uptime-monitor"]
    assert dep.status == "failed" and dep.expires_at is None
    assert sweep(services).stopped == []


def test_lost_jobs_are_recovered(user, services):
    user.post("/api/deployments/uptime-monitor", json={"settings": UPTIME})
    with services.db.session() as db:
        dep = db.query(Deployment).one()
        dep.status = "redeploying"
        db.add(
            Job(
                deployment_id=dep.id,
                kind="redeploy",
                status="running",
                created_at=utcnow() - timedelta(hours=1),
            )
        )
        db.commit()
    assert sweep(services).recovered_jobs == 1
    assert deployments(services)["uptime-monitor"].status == "failed"


def test_sweeper_thread_runs_on_its_interval(services, monkeypatch):
    calls = []
    monkeypatch.setattr("workflow_demo.services.sweeper.sweep", lambda svc: calls.append(svc))
    sweeper = Sweeper(services, 0.01)
    sweeper.start()
    import time

    deadline = time.monotonic() + 2
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    sweeper.stop()
    assert calls


def test_orphan_sweep_is_opt_in_and_isolates_platforms(user, services):
    from workflow_demo.adapters.base import OrphanReport
    from workflow_demo.catalog.models import Platform

    calls = []

    def broken(snapshots, older_than, current):
        calls.append(snapshots)
        raise RuntimeError("n8n down")

    def fine(snapshots, older_than, current):
        return OrphanReport(removed=["Make scenario 1 (alice)"], errors=["Make (bob): 429"])

    services.registry.get(Platform.N8N).sweep_orphans = broken
    services.registry.get(Platform.MAKE).sweep_orphans = fine
    report = sweep(services)
    assert not calls and report.orphan_sweep is False  # off unless ORPHAN_SWEEP is set

    services.settings.orphan_sweep = True
    report = sweep(services)
    assert report.errors == ["n8n: n8n down", "Make (bob): 429"]
    assert report.orphans_removed == ["Make scenario 1 (alice)"]


# --------------------------------------------------------------------------- orphans

N8N = "https://n8n.test"


@respx.mock
def test_n8n_orphans_are_removed(make_settings):
    old = (utcnow() - timedelta(hours=2)).isoformat()
    new = utcnow().isoformat()
    respx.get(f"{N8N}/api/v1/workflows").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "w-known", "name": "[demo] Uptime · alice", "createdAt": old},
                        {"id": "w-orphan", "name": "[demo] Uptime · bob", "createdAt": old},
                    ],
                    "nextCursor": "page-2",
                },
            ),
            httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "w-young", "name": "[demo] Uptime · carol", "createdAt": new},
                        {"id": "w-owner", "name": "Owner's own workflow", "createdAt": old},
                    ],
                    "nextCursor": None,
                },
            ),
        ]
    )
    respx.get(f"{N8N}/api/v1/credentials").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "c-known", "name": "demo · alice · uptime-monitor · slack", "createdAt": old},
                    {"id": "c-orphan", "name": "demo · bob · uptime-monitor · slack", "createdAt": old},
                    {"id": "c-owner", "name": "Owner Slack", "createdAt": old},
                ]
            },
        )
    )
    deleted_workflow = respx.delete(f"{N8N}/api/v1/workflows/w-orphan").mock(return_value=httpx.Response(200))
    deleted_credential = respx.delete(f"{N8N}/api/v1/credentials/c-orphan").mock(
        return_value=httpx.Response(200)
    )
    http = httpx.Client()
    adapter = N8nAdapter(make_settings(), N8nClient(N8N, "k", http), http)
    # A deployment of a workflow the catalog no longer has still protects its items.
    retired = snapshot("alice", None, "active", {"workflow_id": "w-known", "credential_ids": ["c-known"]})
    report = adapter.sweep_orphans([retired], utcnow() - timedelta(hours=1))
    assert report.removed == [
        "n8n workflow [demo] Uptime · bob",
        "n8n credential demo · bob · uptime-monitor · slack",
    ]
    assert report.errors == []
    assert deleted_workflow.called and deleted_credential.called


@respx.mock
def test_n8n_orphan_delete_failures_dont_stop_the_rest(make_settings):
    old = (utcnow() - timedelta(hours=2)).isoformat()
    respx.get(f"{N8N}/api/v1/workflows").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "w1", "name": "[demo] a", "createdAt": old}]})
    )
    respx.get(f"{N8N}/api/v1/credentials").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "c1", "name": "demo · a", "createdAt": old}]})
    )
    respx.delete(f"{N8N}/api/v1/workflows/w1").mock(
        return_value=httpx.Response(500, json={"message": "boom"})
    )
    credential = respx.delete(f"{N8N}/api/v1/credentials/c1").mock(return_value=httpx.Response(200))
    http = httpx.Client()
    report = N8nAdapter(make_settings(), N8nClient(N8N, "k", http), http).sweep_orphans([], utcnow())
    assert credential.called
    assert report.removed == ["n8n credential demo · a"]
    assert report.errors and "boom" in report.errors[0]


BRIDGE = "https://us2.make.com/portal/api/bridge"


def snapshot(username, workflow, status, refs, updated_at=None):
    return DeploymentSnapshot(
        username=username,
        workflow_id=workflow.id if workflow else "retired-workflow",
        workflow=workflow,
        status=status,
        refs=refs,
        updated_at=updated_at or utcnow(),
    )


@respx.mock
def test_make_orphans_are_removed(make_settings):
    adapter = MakeBridgeAdapter(
        make_settings(make_bridge_key_id="k", make_bridge_secret="s", make_bridge_template_id=1),
        httpx.Client(),
    )
    name = "[demo] GitHub merge → Slack · alice"
    respx.get(f"{BRIDGE}/integrations/").mock(
        return_value=httpx.Response(
            200,
            json={
                "integrations": [{"scenario": {"id": 5, "name": name}}, {"scenario": {"id": 6, "name": name}}]
            },
        )
    )
    stray = respx.delete(f"{BRIDGE}/integrations/6").mock(return_value=httpx.Response(200, json={}))
    make = CATALOG.workflow("github-merge-slack")
    active = snapshot("alice", make, "active", {"scenario_id": 5})
    in_flight = snapshot("bob", make, "awaiting_user", {"flow_id": "f"})
    other = snapshot("alice", CATALOG.workflow("uptime-monitor"), "active", {})
    report = adapter.sweep_orphans([active, in_flight, other], utcnow())
    assert report.removed == ["Make scenario 6 (alice)"] and report.errors == []
    assert stray.called

    # Re-checked right before deleting: a popup that just started protects the scenarios.
    stray.reset()
    started = snapshot("alice", make, "awaiting_user", {"flow_id": "f2"})
    report = adapter.sweep_orphans([active], utcnow(), current=lambda username: [started])
    assert report.removed == [] and not stray.called

    # A failed delete is an error, not a removal.
    respx.delete(f"{BRIDGE}/integrations/6").mock(return_value=httpx.Response(500, json={}))
    report = adapter.sweep_orphans([active], utcnow())
    assert report.removed == [] and "delete failed" in report.errors[0]

    # Users without recent Make activity aren't listed at all.
    listing = respx.get(f"{BRIDGE}/integrations/")
    listing.reset()
    stale = snapshot("carol", make, "stopped", {}, updated_at=utcnow() - timedelta(days=3))
    assert adapter.sweep_orphans([stale], utcnow()).removed == [] and not listing.called
