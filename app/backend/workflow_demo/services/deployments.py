"""Deployment lifecycle: requests from the API and the background jobs that carry them out."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from workflow_demo.adapters.base import (
    AdapterError,
    Availability,
    ConnectionInfo,
    DeployContext,
    DeployResult,
    RunStarted,
    RunSummary,
)
from workflow_demo.catalog.models import ConnectorKind, WorkflowEntry
from workflow_demo.db import Deployment, DeploymentEvent, Job, User, utcnow
from workflow_demo.services.container import AppServices
from workflow_demo.services.settings_schema import validate_settings
from workflow_demo.services.states import BUSY, Status, check_transition

log = logging.getLogger(__name__)


class DeploymentError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ----------------------------------------------------------------------------- helpers


def workflow_entry(svc: AppServices, workflow_id: str) -> WorkflowEntry:
    try:
        return svc.catalog.workflow(workflow_id)
    except KeyError:
        raise DeploymentError(f"Unknown workflow {workflow_id!r}", 404) from None


def availability(svc: AppServices, entry: WorkflowEntry) -> Availability:
    try:
        return svc.registry.get(entry.platform).check_available()
    except AdapterError as exc:
        return Availability(False, str(exc))


def required_connectors(svc: AppServices, entry: WorkflowEntry) -> list[str]:
    """Connectors the demo itself must hold (Make-popup connectors live on the platform)."""
    return [
        c.id
        for c in entry.connectors
        if svc.catalog.connectors[c.id].kind is not ConnectorKind.PLATFORM_POPUP
    ]


def missing_connectors(svc: AppServices, user: User, entry: WorkflowEntry) -> list[str]:
    have = {c.connector for c in user.connections if c.status == "active"}
    return [c for c in required_connectors(svc, entry) if c not in have]


def get_deployment(db: Session, user: User, workflow_id: str) -> Deployment | None:
    return db.scalar(
        select(Deployment).where(Deployment.user_id == user.id, Deployment.workflow_id == workflow_id)
    )


def add_event(dep: Deployment, type_: str, message: str, **details: Any) -> None:
    dep.events.append(DeploymentEvent(type=type_, message=message, details=details))


def set_status(dep: Deployment, new: Status) -> None:
    check_transition(dep.status, new)
    dep.status = new


def build_context(dep: Deployment, entry: WorkflowEntry, refs: dict[str, Any] | None = None) -> DeployContext:
    return DeployContext(
        username=dep.user.username,
        workflow=entry,
        deployment_id=dep.id,
        settings=dict(dep.inputs or {}),
        connections={
            c.connector: ConnectionInfo(
                connector=c.connector,
                method=c.method,
                details=dict(c.details or {}),
                nango_integration=c.nango_integration,
                nango_connection_id=c.nango_connection_id,
            )
            for c in dep.user.connections
            if c.status == "active"
        },
        refs=dict(dep.platform_refs if refs is None else refs),
    )


# ------------------------------------------------------------------------- API requests


def request_deploy(
    svc: AppServices, db: Session, user: User, workflow_id: str, raw: dict[str, Any]
) -> Deployment:
    """Deploy, or redeploy if a deployment exists. The work happens in a background job."""
    entry = workflow_entry(svc, workflow_id)
    avail = availability(svc, entry)
    if not avail.available:
        raise DeploymentError(avail.reason or "Deploy unavailable")
    cleaned = validate_settings(entry.settings, raw)  # SettingsError -> 422 in the API layer
    missing = missing_connectors(svc, user, entry)
    if missing:
        names = ", ".join(svc.catalog.connectors[m].name for m in missing)
        raise DeploymentError(f"Connect first: {names}")

    dep = get_deployment(db, user, workflow_id)
    if dep is not None and dep.status in BUSY:
        raise DeploymentError("This deployment is busy; wait for the current step to finish")
    if dep is None or dep.status == Status.STOPPED:
        if dep is None:
            dep = Deployment(user_id=user.id, workflow_id=workflow_id, status=Status.STOPPED)
            db.add(dep)
        set_status(dep, Status.DEPLOYING)
        kind = "deploy"
        add_event(dep, "requested", "Deploy requested")
    else:
        set_status(dep, Status.REDEPLOYING)
        kind = "redeploy"
        add_event(dep, "requested", "Redeploy requested")
    dep.inputs = cleaned
    dep.error = None
    job = Job(kind=kind)
    try:
        db.flush()
        job.deployment_id = dep.id
        db.add(job)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DeploymentError("Another deploy request is in progress") from None
    svc.runner.submit(job.id)
    db.refresh(dep)
    return dep


def request_delete(svc: AppServices, db: Session, user: User, workflow_id: str) -> Deployment:
    workflow_entry(svc, workflow_id)
    dep = get_deployment(db, user, workflow_id)
    if dep is None:
        raise DeploymentError("Not deployed", 404)
    if dep.status == Status.STOPPED:
        return dep
    if dep.status in BUSY:
        raise DeploymentError("This deployment is busy; wait for the current step to finish")
    set_status(dep, Status.STOPPING)
    add_event(dep, "requested", "Delete requested")
    job = Job(deployment_id=dep.id, kind="undeploy")
    db.add(job)
    db.commit()
    svc.runner.submit(job.id)
    db.refresh(dep)
    return dep


def finish_user_step(svc: AppServices, db: Session, deployment_id: int, params: dict[str, str]) -> Deployment:
    """Called when the user comes back from the platform's popup (Make Bridge)."""
    dep = db.get(Deployment, deployment_id)
    if dep is None:
        raise DeploymentError("Unknown deployment", 404)
    if dep.status != Status.AWAITING_USER:
        raise DeploymentError("This deployment isn't waiting for you")
    entry = workflow_entry(svc, dep.workflow_id)
    try:
        result = svc.registry.get(entry.platform).finish_user_step(build_context(dep, entry), params)
    except AdapterError as exc:
        _fail(dep, str(exc))
        db.commit()
        raise DeploymentError(str(exc), 502) from None
    _apply_result(svc, dep, result)
    db.commit()
    return dep


def run_now(svc: AppServices, db: Session, user: User, workflow_id: str) -> RunStarted:
    entry = workflow_entry(svc, workflow_id)
    if not entry.run_now:
        raise DeploymentError("This workflow can't be started from the demo", 400)
    dep = get_deployment(db, user, workflow_id)
    if dep is None or dep.status != Status.ACTIVE:
        raise DeploymentError("Deploy the workflow first")
    try:
        started = svc.registry.get(entry.platform).run_now(build_context(dep, entry))
    except AdapterError as exc:
        raise DeploymentError(str(exc), 502) from None
    if started.refs_update:
        dep.platform_refs = {**dep.platform_refs, **started.refs_update}
    add_event(dep, "run_started", started.message, run_id=started.run_id)
    db.commit()
    return started


def recent_runs(svc: AppServices, db: Session, user: User, workflow_id: str) -> list[RunSummary]:
    entry = workflow_entry(svc, workflow_id)
    dep = get_deployment(db, user, workflow_id)
    if dep is None or dep.status != Status.ACTIVE:
        return []
    try:
        return svc.registry.get(entry.platform).recent_runs(build_context(dep, entry))
    except AdapterError as exc:
        raise DeploymentError(str(exc), 502) from None


# ------------------------------------------------------------------------- background job


def run_job(svc: AppServices, job_id: int) -> None:
    with svc.db.session() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "queued":
            return
        dep = db.get(Deployment, job.deployment_id)
        entry = svc.catalog.workflow(dep.workflow_id)
        job.status = "running"
        job.started_at = utcnow()
        db.commit()
        try:
            adapter = svc.registry.get(entry.platform)
            if job.kind in ("redeploy", "undeploy", "expire") and dep.platform_refs:
                adapter.undeploy(build_context(dep, entry))
                dep.platform_refs = {}
                add_event(dep, "removed", "Removed the previous deployment from the platform")
            if job.kind in ("deploy", "redeploy"):
                _apply_result(svc, dep, adapter.deploy(build_context(dep, entry, refs={})))
            else:
                set_status(dep, Status.STOPPED)
                dep.expires_at = None
                if job.kind == "expire":
                    add_event(dep, "expired", "Stopped automatically after the demo time limit")
                else:
                    add_event(dep, "stopped", "Deployment deleted")
            job.status = "succeeded"
        except AdapterError as exc:
            _fail(dep, str(exc))
            job.status, job.error = "failed", str(exc)
        except Exception as exc:  # noqa: BLE001 - surface any failure on the deployment
            log.exception("job %s failed", job_id)
            _fail(dep, f"Unexpected error: {exc.__class__.__name__}")
            job.status, job.error = "failed", repr(exc)
        finally:
            job.finished_at = utcnow()
            db.commit()


def _apply_result(svc: AppServices, dep: Deployment, result: DeployResult) -> None:
    dep.platform_refs = result.refs
    if result.status == "awaiting_user":
        set_status(dep, Status.AWAITING_USER)
        add_event(dep, "awaiting_user", result.message or "Waiting for you to finish on the platform")
        return
    set_status(dep, Status.ACTIVE)
    now = utcnow()
    dep.deployed_at = now
    dep.expires_at = now + timedelta(hours=svc.settings.deployment_ttl_hours)
    add_event(dep, "active", result.message or "Deployed")


def _fail(dep: Deployment, message: str) -> None:
    set_status(dep, Status.FAILED)
    dep.error = message
    add_event(dep, "failed", message)
