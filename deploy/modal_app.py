"""The demo itself on Modal: web app (API + built frontend), deploy jobs, and the sweeper.

    (cd app/frontend && npm ci && npm run build)        # the image serves app/frontend/dist
    modal secret create workflow-demo-app --from-dotenv deploy/production.env   # see docs/go-live.md
    modal run deploy/modal_app.py::migrate              # alembic upgrade head on Neon
    modal deploy deploy/modal_app.py                    # prints the web URL → PUBLIC_BASE_URL

Each deploy/undeploy job runs in its own function call (``run_job.spawn``), so it survives the
web container scaling down. The sweeper runs on a schedule instead of in the web process, because
there can be several web containers (or none).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import modal

APP_NAME = "workflow-demo"
REPO = "/repo"

# Local paths are only read when building (`modal deploy`), not inside the running containers.
LOCAL_REPO = Path(__file__).resolve().parent.parent
if modal.is_local() and not (LOCAL_REPO / "app/frontend/dist/index.html").exists():
    raise SystemExit("Build the frontend first: cd app/frontend && npm ci && npm run build")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_pyproject(str(LOCAL_REPO / "app/backend/pyproject.toml"))
    .env(
        {
            "PYTHONPATH": f"{REPO}/app/backend",
            "WORKFLOW_DEMO_REPO_ROOT": REPO,
            "WORKFLOW_DEMO_CATALOG_DIR": f"{REPO}/catalog",
            "WORKFLOW_DEMO_FRONTEND_DIST": f"{REPO}/app/frontend/dist",
            # Several containers share the database: never fail jobs another container is running,
            # and sweep from the scheduled function below instead of each web container.
            "RECOVER_JOBS_ON_STARTUP": "false",
            "SWEEP_INTERVAL_SECONDS": "0",
        }
    )
    .add_local_dir(
        LOCAL_REPO / "app/backend",
        f"{REPO}/app/backend",
        ignore=[".venv", "**/__pycache__", "*.db", ".env", "tests"],
    )
    .add_local_dir(LOCAL_REPO / "catalog", f"{REPO}/catalog")
    .add_local_dir(LOCAL_REPO / "app/frontend/dist", f"{REPO}/app/frontend/dist")
)

app = modal.App(APP_NAME, image=image, secrets=[modal.Secret.from_name("workflow-demo-app")])


class ModalJobRunner:
    """Runs each job in its own ``run_job`` function call."""

    def __init__(self, run) -> None:  # the in-process runner callable isn't needed here
        pass

    def submit(self, job_id: int) -> None:
        run_job.spawn(job_id)


def services():
    from workflow_demo.app import build_services
    from workflow_demo.config import get_settings

    return build_services(get_settings(), runner_factory=ModalJobRunner)


@app.function(timeout=15 * 60, max_containers=10)
def run_job(job_id: int) -> None:
    from workflow_demo.services.deployments import run_job as run

    svc = services()
    try:
        run(svc, job_id)
    finally:
        svc.http.close()


@app.function(schedule=modal.Cron("*/10 * * * *"), timeout=10 * 60)
def sweeper() -> None:
    from workflow_demo.services.sweeper import sweep

    svc = services()
    try:
        sweep(svc)
    finally:
        svc.http.close()


@app.function(timeout=10 * 60)
def migrate() -> None:
    subprocess.run(["alembic", "upgrade", "head"], cwd=f"{REPO}/app/backend", check=True)


@app.function(scaledown_window=10 * 60, timeout=5 * 60)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    from workflow_demo.app import create_app

    svc = services()
    return create_app(svc.settings, svc)
