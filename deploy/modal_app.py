"""The demo itself on Modal: web app (API + built frontend), deploy jobs, and the sweeper.

    (cd app/frontend && npm ci && npm run build)        # the image serves app/frontend/dist
    modal secret create workflow-demo-app --from-dotenv deploy/production.env   # see docs/go-live.md
    modal run deploy/modal_app.py::migrate              # alembic upgrade head on Neon
    modal deploy deploy/modal_app.py                    # prints the web URL → PUBLIC_BASE_URL

Each deploy/undeploy job runs in its own function call (``Jobs.run.spawn``), so it survives the
web container scaling down. The sweeper runs on a schedule instead of in the web process, because
there can be several web containers (or none).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import modal

APP_NAME = "workflow-demo"
REPO = "/repo"
SWEEP_SCHEDULE = "*/30 * * * *"  # also lets Neon's compute suspend between runs

# Local paths are only read when building (`modal deploy`), not inside the running containers.
LOCAL_REPO = Path(__file__).resolve().parent.parent
DIST = LOCAL_REPO / "app/frontend/dist"
if modal.is_local() and sys.argv[1:2] in (["deploy"], ["serve"]) and not (DIST / "index.html").exists():
    raise SystemExit("Build the frontend first: cd app/frontend && npm ci && npm run build")

LOCAL_FILES = ["**/.venv", "**/__pycache__", "**/.*_cache", "**/*.egg-info", "**/*.db*", "**/.env*", "tests"]

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_pyproject(str(LOCAL_REPO / "app/backend/pyproject.toml"))
    .env(
        {
            "PYTHONPATH": f"{REPO}/app/backend",
            "WORKFLOW_DEMO_REPO_ROOT": REPO,
            "WORKFLOW_DEMO_CATALOG_DIR": f"{REPO}/catalog",
            "WORKFLOW_DEMO_FRONTEND_DIST": f"{REPO}/app/frontend/dist",
        }
    )
    .add_local_dir(LOCAL_REPO / "app/backend", f"{REPO}/app/backend", ignore=LOCAL_FILES)
    .add_local_dir(LOCAL_REPO / "catalog", f"{REPO}/catalog", ignore=LOCAL_FILES)
    .add_local_dir(DIST, f"{REPO}/app/frontend/dist")
)

app = modal.App(APP_NAME, image=image, secrets=[modal.Secret.from_name("workflow-demo-app")])


def _check_database(url: str) -> None:
    if not url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        # Without it every container would quietly use its own throwaway SQLite file.
        raise RuntimeError("DATABASE_URL in the workflow-demo-app secret must be the Neon Postgres URL")


class ModalJobRunner:
    """Runs each job in its own ``Jobs.run`` function call."""

    def __init__(self, run) -> None:  # the in-process runner callable isn't needed here
        pass

    def submit(self, job_id: int) -> None:
        Jobs().run.spawn(job_id)


def services():
    from workflow_demo.app import build_services
    from workflow_demo.config import get_settings

    settings = get_settings()
    _check_database(settings.database_url)
    # Several containers share the database. Set here rather than via environment variables, which
    # the secret could override: never fail jobs another container is running, and sweep only from
    # the scheduled function below.
    settings.recover_jobs_on_startup = False
    settings.sweep_interval_seconds = 0
    return build_services(settings, runner_factory=ModalJobRunner)


def close(svc) -> None:
    svc.http.close()
    svc.db.engine.dispose()


@app.cls(timeout=15 * 60, max_containers=10, scaledown_window=5 * 60)
class Jobs:
    """Deploy jobs; services (DB pool, catalog, adapters) are built once per container."""

    @modal.enter()
    def start(self) -> None:
        self.svc = services()

    @modal.exit()
    def stop(self) -> None:
        close(self.svc)

    @modal.method()
    def run(self, job_id: int) -> None:
        from workflow_demo.services.deployments import run_job

        run_job(self.svc, job_id)


@app.function(schedule=modal.Cron(SWEEP_SCHEDULE), timeout=10 * 60)
def sweeper() -> None:
    from workflow_demo.services.sweeper import sweep

    svc = services()
    try:
        sweep(svc)
    finally:
        close(svc)


@app.function(timeout=10 * 60)
def migrate() -> None:
    """``alembic upgrade head``; uses MIGRATION_DATABASE_URL (Neon's direct, non-pooled URL) if set."""
    url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    _check_database(url)
    env = {**os.environ, "DATABASE_URL": url}
    subprocess.run(["alembic", "upgrade", "head"], cwd=f"{REPO}/app/backend", env=env, check=True)


@app.function(scaledown_window=10 * 60, timeout=5 * 60)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    from workflow_demo.app import create_app

    svc = services()
    return create_app(svc.settings, svc)
