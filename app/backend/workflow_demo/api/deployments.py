"""Deploy / redeploy / delete, Run now, recent runs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from workflow_demo.api.deps import DB, CurrentUser, Services
from workflow_demo.api.schemas import DeploymentOut, DeployRequest, RunOut, RunStartedOut
from workflow_demo.api.workflows import deployment_out
from workflow_demo.services import deployments as svc_deployments
from workflow_demo.services.deployments import DeploymentError
from workflow_demo.services.settings_schema import SettingsError

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


def _raise(exc: DeploymentError) -> None:
    raise HTTPException(exc.status_code, exc.message) from None


@router.post("/{workflow_id}", response_model=DeploymentOut, status_code=202)
def deploy(workflow_id: str, body: DeployRequest, svc: Services, db: DB, user: CurrentUser) -> DeploymentOut:
    try:
        dep = svc_deployments.request_deploy(svc, db, user, workflow_id, body.settings)
    except SettingsError as exc:
        raise HTTPException(422, {"message": "Check the settings", "fields": exc.errors}) from None
    except DeploymentError as exc:
        _raise(exc)
    return deployment_out(dep, with_events=True)


@router.get("/{workflow_id}", response_model=DeploymentOut)
def get(workflow_id: str, svc: Services, db: DB, user: CurrentUser) -> DeploymentOut:
    dep = svc_deployments.get_deployment(db, user, workflow_id)
    if dep is None:
        raise HTTPException(404, "Not deployed")
    return deployment_out(dep, with_events=True)


@router.delete("/{workflow_id}", response_model=DeploymentOut, status_code=202)
def delete(workflow_id: str, svc: Services, db: DB, user: CurrentUser) -> DeploymentOut:
    try:
        dep = svc_deployments.request_delete(svc, db, user, workflow_id)
    except DeploymentError as exc:
        _raise(exc)
    return deployment_out(dep, with_events=True)


@router.post("/{workflow_id}/run", response_model=RunStartedOut, status_code=202)
def run(workflow_id: str, svc: Services, db: DB, user: CurrentUser) -> RunStartedOut:
    try:
        started = svc_deployments.run_now(svc, db, user, workflow_id)
    except DeploymentError as exc:
        _raise(exc)
    return RunStartedOut(run_id=started.run_id, message=started.message)


@router.get("/{workflow_id}/runs", response_model=list[RunOut])
def runs(workflow_id: str, svc: Services, db: DB, user: CurrentUser) -> list[RunOut]:
    try:
        found = svc_deployments.recent_runs(svc, db, user, workflow_id)
    except DeploymentError as exc:
        _raise(exc)
    return [RunOut(**r.__dict__) for r in found]
