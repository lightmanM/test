"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from workflow_demo.adapters.registry import AdapterRegistry, fake_registry
from workflow_demo.api import admin, auth, connections, deployments, user_steps, workflows
from workflow_demo.catalog.loader import load_catalog
from workflow_demo.config import Settings, get_settings
from workflow_demo.db import Database
from workflow_demo.security import Signer
from workflow_demo.services import deployments as svc_deployments
from workflow_demo.services.container import AppServices
from workflow_demo.services.jobs import ThreadJobRunner

log = logging.getLogger(__name__)


def build_services(
    settings: Settings,
    *,
    registry: AdapterRegistry | None = None,
    runner_factory=None,
    database: Database | None = None,
) -> AppServices:
    svc = AppServices(
        settings=settings,
        db=database or Database(settings.database_url),
        catalog=load_catalog(),
        registry=registry or AdapterRegistry({}),
        signer=Signer(settings.session_secret.get_secret_value()),
    )
    if registry is None and settings.fake_platforms:
        svc.registry = fake_registry(lambda dep_id: fake_popup_url(svc, dep_id))
    run = lambda job_id: svc_deployments.run_job(svc, job_id)  # noqa: E731
    svc.runner = (runner_factory or ThreadJobRunner)(run)
    return svc


def fake_popup_url(svc: AppServices, deployment_id: int) -> str:
    return f"{svc.settings.base_url}/fake/make-popup?state={user_steps.user_step_state(svc, deployment_id)}"


def create_app(settings: Settings | None = None, services: AppServices | None = None) -> FastAPI:
    settings = settings or get_settings()
    svc = services or build_services(settings)
    app = FastAPI(title="Workflow Deploy Demo", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.services = svc
    for module in (auth, workflows, connections, deployments, admin, user_steps):
        app.include_router(module.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "fake_platforms": svc.settings.fake_platforms}

    return app
