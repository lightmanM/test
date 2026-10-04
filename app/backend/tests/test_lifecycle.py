"""Lifecycle edge cases: concurrency, stale jobs, expiry, popup tokens, settings on redeploy."""

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from workflow_demo.app import build_services
from workflow_demo.db import Deployment, Job, normalize_database_url
from workflow_demo.services import deployments as svc_deployments

UPTIME = {"slack_channel": "C0123ABCD"}


class QueueRunner:
    """Collects jobs instead of running them, so tests control when they run."""

    def __init__(self, run):
        self.run = run
        self.queued: list[int] = []

    def submit(self, job_id):
        self.queued.append(job_id)

    def drain(self):
        while self.queued:
            self.run(self.queued.pop(0))


@pytest.fixture
def queued(make_settings):
    from fastapi.testclient import TestClient

    from workflow_demo.app import create_app

    svc = build_services(make_settings(recover_jobs_on_startup=False), runner_factory=QueueRunner)
    svc.db.create_all()
    with TestClient(create_app(svc.settings, svc)) as client:
        client.post("/api/auth/login", json={"username": "alice", "passcode": "pass"})
        for connector in ("google", "slack"):
            client.post(f"/api/connections/{connector}/fake")
        yield svc, client


def deployment(svc) -> Deployment:
    with svc.db.session() as db:
        return db.query(Deployment).one()


def test_second_request_while_queued_is_rejected(queued):
    svc, client = queued
    client.post("/api/deployments/uptime-monitor", json={"settings": UPTIME})
    svc.runner.drain()
    assert client.post("/api/deployments/uptime-monitor", json={"settings": UPTIME}).status_code == 202
    assert client.post("/api/deployments/uptime-monitor", json={"settings": UPTIME}).status_code == 409
    assert client.delete("/api/deployments/uptime-monitor").status_code == 409
    assert len(svc.runner.queued) == 1
    svc.runner.drain()
    assert deployment(svc).status == "active"


def test_claim_rejects_stale_read(queued):
    svc, client = queued
    client.post("/api/deployments/uptime-monitor", json={"settings": UPTIME})
    svc.runner.drain()
    with svc.db.session() as first, svc.db.session() as second:
        dep_a = first.query(Deployment).one()
        dep_b = second.query(Deployment).one()  # both read "active"
        svc_deployments.claim_status(first, dep_a, svc_deployments.Status.REDEPLOYING)
        first.commit()
        with pytest.raises(svc_deployments.DeploymentError):
            svc_deployments.claim_status(second, dep_b, svc_deployments.Status.REDEPLOYING)


def test_job_for_wrong_state_is_skipped(queued):
    svc, client = queued
    client.post("/api/deployments/uptime-monitor", json={"settings": UPTIME})
    svc.runner.drain()
    with svc.db.session() as db:
        dep = db.query(Deployment).one()
        db.add(Job(deployment_id=dep.id, kind="deploy"))
        db.commit()
        job_id = db.query(Job).order_by(Job.id.desc()).first().id
    svc_deployments.run_job(svc, job_id)
    with svc.db.session() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed" and job.error.startswith("skipped")
    assert deployment(svc).status == "active"  # untouched


def test_stale_jobs_are_recovered(queued):
    svc, client = queued
    client.post("/api/deployments/uptime-monitor", json={"settings": UPTIME})
    assert deployment(svc).status == "deploying"
    assert svc_deployments.recover_stale_jobs(svc, older_than=timedelta(0)) == 1
    dep = deployment(svc)
    assert dep.status == "failed" and "Interrupted" in dep.error
    svc.runner.queued.clear()
    assert client.post("/api/deployments/uptime-monitor", json={"settings": UPTIME}).status_code == 202


def test_expire_stops_an_active_deployment(queued):
    svc, client = queued
    client.post("/api/deployments/uptime-monitor", json={"settings": UPTIME})
    svc.runner.drain()
    with svc.db.session() as db:
        assert svc_deployments.request_expire(svc, db, db.query(Deployment).one()) is True
    svc.runner.drain()
    dep = deployment(svc)
    assert dep.status == "stopped" and dep.platform_refs == {} and dep.expires_at is None
    with svc.db.session() as db:
        assert svc_deployments.request_expire(svc, db, db.query(Deployment).one()) is False


def test_redeploy_undeploys_with_the_old_settings(queued):
    svc, client = queued
    from workflow_demo.catalog.models import Platform

    adapter = svc.registry.get(Platform.N8N)
    seen = []
    original_undeploy = adapter.undeploy
    adapter.undeploy = lambda ctx: (seen.append(ctx.settings["sites"]), original_undeploy(ctx))
    client.post(
        "/api/deployments/uptime-monitor", json={"settings": {**UPTIME, "sites": ["https://old.dev"]}}
    )
    svc.runner.drain()
    client.post(
        "/api/deployments/uptime-monitor", json={"settings": {**UPTIME, "sites": ["https://new.dev"]}}
    )
    assert deployment(svc).inputs["sites"] == ["https://old.dev"]  # not overwritten before the job
    svc.runner.drain()
    assert seen == [["https://old.dev"]]
    assert deployment(svc).inputs["sites"] == ["https://new.dev"]


def test_popup_link_from_an_earlier_deploy_is_rejected(queued):
    svc, client = queued

    def popup_state():
        url = client.get("/api/deployments/github-merge-slack").json()["popup_url"]
        return parse_qs(urlparse(url).query)["state"][0]

    client.post("/api/deployments/github-merge-slack", json={"settings": {}})
    svc.runner.drain()
    old_state = popup_state()
    client.post("/api/deployments/github-merge-slack", json={"settings": {}})  # redeploy from awaiting_user
    svc.runner.drain()
    new_state = popup_state()
    assert old_state != new_state
    page = client.get(f"/make/callback?state={old_state}")
    assert page.status_code == 400 and "earlier deploy" in page.text
    assert client.get(f"/make/callback?state={new_state}").status_code == 200
    # The callback answers at once; a job finishes the deploy. A repeated redirect is harmless.
    assert deployment(svc).status == "deploying"
    assert client.get(f"/make/callback?state={new_state}").status_code == 200
    assert len(svc.runner.queued) == 1
    svc.runner.drain()
    assert deployment(svc).status == "active"
    assert "user_step_nonce" not in deployment(svc).platform_refs


def test_normalize_database_url():
    assert normalize_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("postgresql://u:p@h/db?sslmode=require") == (
        "postgresql+psycopg://u:p@h/db?sslmode=require"
    )
    assert normalize_database_url("postgresql+psycopg://h/db") == "postgresql+psycopg://h/db"
    assert normalize_database_url("sqlite:///x.db") == "sqlite:///x.db"


def test_database_settings_read_dotenv(tmp_path, monkeypatch):
    from workflow_demo.config import DatabaseSettings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql://neon.example/db\n")
    assert DatabaseSettings().database_url == "postgresql://neon.example/db"


def test_job_that_cant_start_fails_at_once(make_settings):
    from fastapi.testclient import TestClient

    from workflow_demo.app import create_app

    class Refusing:
        def __init__(self, run):
            pass

        def submit(self, job_id):
            raise RuntimeError("job platform unavailable")

    svc = build_services(make_settings(recover_jobs_on_startup=False), runner_factory=Refusing)
    svc.db.create_all()
    with TestClient(create_app(svc.settings, svc)) as client:
        client.post("/api/auth/login", json={"username": "alice", "passcode": "pass"})
        for connector in ("google", "slack"):
            client.post(f"/api/connections/{connector}/fake")
        resp = client.post("/api/deployments/uptime-monitor", json={"settings": UPTIME})
        assert resp.status_code == 503
        dep = deployment(svc)
        assert dep.status == "failed" and "try again" in dep.error
        with svc.db.session() as db:
            assert db.query(Job).one().status == "failed"
