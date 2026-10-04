"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from workflow_demo import paths
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
        svc.registry = fake_registry(lambda state: f"{settings.base_url}/fake/make-popup?state={state}")
    run = lambda job_id: svc_deployments.run_job(svc, job_id)  # noqa: E731
    svc.runner = (runner_factory or ThreadJobRunner)(run)
    return svc


def create_app(settings: Settings | None = None, services: AppServices | None = None) -> FastAPI:
    settings = settings or get_settings()
    svc = services or build_services(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if svc.settings.recover_jobs_on_startup:
            svc_deployments.recover_stale_jobs(svc, older_than=timedelta(0))
        yield

    app = FastAPI(
        title="Workflow Deploy Demo", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan
    )
    app.state.services = svc
    for module in (auth, workflows, connections, deployments, admin, user_steps):
        app.include_router(module.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "fake_platforms": svc.settings.fake_platforms}

    mount_frontend(app, paths.FRONTEND_DIST)
    return app


SERVER_PREFIXES = ("api/", "make/", "fake/")


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built React app (``npm run build``) with client-side routing fallback."""
    index = dist / "index.html"
    if not index.exists():
        log.info("frontend build not found at %s; serving the API only", dist)
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith(SERVER_PREFIXES):
            raise HTTPException(404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)
