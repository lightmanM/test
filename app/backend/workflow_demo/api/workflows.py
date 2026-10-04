"""Catalog API with the signed-in user's readiness and deployment status."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from workflow_demo.api.deps import DB, CurrentUser, Services
from workflow_demo.api.schemas import (
    ConnectorStatus,
    DeploymentOut,
    EventOut,
    Link,
    SettingOut,
    WorkflowDetail,
    WorkflowSummary,
)
from workflow_demo.catalog.models import ConnectorKind, Platform, WorkflowEntry
from workflow_demo.db import Connection, Deployment
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
        links=user_links(dep),
        updated_at=dep.updated_at,
        events=[EventOut(at=e.at, type=e.type, message=e.message) for e in dep.events[-30:]]
        if with_events
        else [],
    )


# Platform refs a user may open (never the owner's platform pages, which they can't access).
USER_LINKS = {"spreadsheet_url": "Your uptime spreadsheet"}


def user_links(dep: Deployment) -> list[Link]:
    refs = dep.platform_refs or {}
    return [
        Link(label=label, url=refs[key])
        for key, label in USER_LINKS.items()
        if isinstance(refs.get(key), str) and refs[key].startswith("https://")
    ]


def summary(svc: AppServices, entry: WorkflowEntry, active: dict[str, Connection]) -> dict:
    connectors = []
    for wc in entry.connectors:
        connector = svc.catalog.connectors[wc.id]
        by_platform = connector.kind is ConnectorKind.PLATFORM_POPUP
        record = active.get(wc.id)
        connectors.append(
            ConnectorStatus(
                id=connector.id,
                name=connector.name,
                kind=connector.kind.value,
                description=connector.description,
                purpose=wc.purpose,
                help=connector.help,
                connected=record is not None,
                label=(record.details or {}).get("label") if record is not None else None,
                secret=connector.secret,
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
        "ready": not svc_deployments.missing_connectors(svc, entry, set(active)),
        "connectors": connectors,
    }


@router.get("/workflows", response_model=list[WorkflowSummary])
def list_workflows(svc: Services, db: DB, user: CurrentUser) -> list[WorkflowSummary]:
    deps = {d.workflow_id: d for d in user.deployments}
    active = svc_deployments.active_connections(user)
    return [
        WorkflowSummary(**summary(svc, entry, active), deployment=deployment_out(deps.get(entry.id)))
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
        **summary(svc, entry, svc_deployments.active_connections(user)),
        deployment=deployment_out(dep, with_events=True),
        description=entry.description,
        settings=[SettingOut(**s.model_dump(mode="json")) for s in entry.settings],
        try_it=entry.try_it,
        run_now=entry.run_now,
        shared_deployment=entry.platform is Platform.MODAL
        and bool(entry.modal and entry.modal.shared_deployment),
    )
