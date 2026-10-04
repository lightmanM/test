"""Catalog API with the signed-in user's readiness and deployment status."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from workflow_demo.api.deps import DB, CurrentUser, Services
from workflow_demo.api.schemas import (
    ConnectorStatus,
    DeploymentOut,
    EventOut,
    SettingOut,
    WorkflowDetail,
    WorkflowSummary,
)
from workflow_demo.catalog.models import ConnectorKind, Platform, WorkflowEntry
from workflow_demo.db import Deployment, User
from workflow_demo.services import deployments as svc_deployments
from workflow_demo.services.container import AppServices
from workflow_demo.services.states import Status

router = APIRouter(prefix="/api", tags=["workflows"])


def deployment_out(dep: Deployment | None, with_events: bool = False) -> DeploymentOut | None:
    if dep is None:
        return None
    return DeploymentOut(
        workflow_id=dep.workflow_id,
        status=dep.status,
        settings=dep.inputs or {},
        error=dep.error,
        deployed_at=dep.deployed_at,
        expires_at=dep.expires_at,
        popup_url=(dep.platform_refs or {}).get("popup_url") if dep.status == Status.AWAITING_USER else None,
        updated_at=dep.updated_at,
        events=[EventOut(at=e.at, type=e.type, message=e.message) for e in dep.events[-30:]]
        if with_events
        else [],
    )


def summary(svc: AppServices, user: User, entry: WorkflowEntry, dep: Deployment | None) -> dict:
    connected = {c.connector for c in user.connections if c.status == "active"}
    connectors = []
    for wc in entry.connectors:
        connector = svc.catalog.connectors[wc.id]
        by_platform = connector.kind is ConnectorKind.PLATFORM_POPUP
        connectors.append(
            ConnectorStatus(
                id=connector.id,
                name=connector.name,
                kind=connector.kind.value,
                description=connector.description,
                purpose=wc.purpose,
                help=connector.help,
                connected=wc.id in connected,
                managed_by_platform=by_platform,
            )
        )
    avail = svc_deployments.availability(svc, entry)
    return {
        "id": entry.id,
        "name": entry.name,
        "summary": entry.summary,
        "platform": entry.platform.value,
        "available": avail.available,
        "unavailable_reason": avail.reason,
        "ready": not svc_deployments.missing_connectors(svc, user, entry),
        "connectors": connectors,
    }


@router.get("/workflows", response_model=list[WorkflowSummary])
def list_workflows(svc: Services, db: DB, user: CurrentUser) -> list[WorkflowSummary]:
    deps = {d.workflow_id: d for d in user.deployments}
    return [
        WorkflowSummary(
            **summary(svc, user, entry, deps.get(entry.id)), deployment=deployment_out(deps.get(entry.id))
        )
        for entry in svc.catalog.workflows
    ]


@router.get("/workflows/{workflow_id}", response_model=WorkflowDetail)
def get_workflow(workflow_id: str, svc: Services, db: DB, user: CurrentUser) -> WorkflowDetail:
    try:
        entry = svc.catalog.workflow(workflow_id)
    except KeyError:
        raise HTTPException(404, "Unknown workflow") from None
    dep = svc_deployments.get_deployment(db, user, workflow_id)
    return WorkflowDetail(
        **summary(svc, user, entry, dep),
        deployment=deployment_out(dep, with_events=True),
        description=entry.description,
        settings=[SettingOut(**s.model_dump(mode="json")) for s in entry.settings],
        try_it=entry.try_it,
        run_now=entry.run_now,
        shared_deployment=entry.platform is Platform.MODAL
        and bool(entry.modal and entry.modal.shared_deployment),
    )
