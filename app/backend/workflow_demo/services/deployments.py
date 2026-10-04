"""Deployment lifecycle: requests from the API and the background jobs that carry them out.

Concurrency rules:
* status changes requested by the API are *claimed* with a conditional UPDATE, so two requests
  can't both start work on the same deployment (the loser gets 409);
* a job only runs if the deployment is in the busy state its kind expects;
* jobs left behind by a crash are failed by ``recover_stale_jobs`` so nothing stays busy forever.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from workflow_demo.adapters.base import (
    AdapterError,
    Availability,
    ConnectionInfo,
    DeployContext,
    DeployResult,
    RunStarted,
    RunSummary,
)
from workflow_demo.catalog.models import ConnectorKind, Platform, WorkflowEntry
from workflow_demo.db import Connection, Deployment, DeploymentEvent, Job, User, utcnow
from workflow_demo.services.connections import UserCredentials
from workflow_demo.services.container import AppServices
from workflow_demo.services.settings_schema import reject_expressions, validate_settings
from workflow_demo.services.states import BUSY, Status, check_transition

log = logging.getLogger(__name__)

USER_STEP_PURPOSE = "user-step"
USER_STEP_MAX_AGE_SECONDS = 3600
NONCE_REF = "user_step_nonce"

# The busy state a deployment must be in for each job kind to run.
JOB_EXPECTS = {
    "deploy": Status.DEPLOYING,
    "redeploy": Status.REDEPLOYING,
    "finish": Status.DEPLOYING,  # after the user's popup step (Make Bridge)
    "undeploy": Status.STOPPING,
    "expire": Status.STOPPING,
}


class DeploymentError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class _SkipJob(Exception):
    """The job no longer applies; fail it without touching the deployment."""


# ----------------------------------------------------------------------------- helpers


def workflow_entry(svc: AppServices, workflow_id: str) -> WorkflowEntry:
    try:
        return svc.catalog.workflow(workflow_id)
    except KeyError:
        raise DeploymentError(f"Unknown workflow {workflow_id!r}", 404) from None


def availability(svc: AppServices, entry: WorkflowEntry) -> Availability:
    try:
        return svc.registry.get(entry.platform).check_available(entry)
    except AdapterError as exc:
        return Availability(False, str(exc))


def required_connectors(svc: AppServices, entry: WorkflowEntry) -> list[str]:
    """Connectors the demo itself must hold (Make-popup connectors live on the platform)."""
    return [
        c.id
        for c in entry.connectors
        if svc.catalog.connectors[c.id].kind is not ConnectorKind.PLATFORM_POPUP
    ]


def active_connections(user: User) -> dict[str, Connection]:
    return {c.connector: c for c in user.connections if c.status == "active"}


def active_connectors(user: User) -> set[str]:
    return set(active_connections(user))


def missing_connectors(svc: AppServices, entry: WorkflowEntry, connected: set[str]) -> list[str]:
    return [c for c in required_connectors(svc, entry) if c not in connected]


def get_deployment(db: Session, user: User, workflow_id: str) -> Deployment | None:
    return db.scalar(
        select(Deployment).where(Deployment.user_id == user.id, Deployment.workflow_id == workflow_id)
    )


def add_event(dep: Deployment, type_: str, message: str, **details: Any) -> None:
    dep.events.append(DeploymentEvent(type=type_, message=message, details=details))


def set_status(dep: Deployment, new: Status) -> None:
    check_transition(dep.status, new)
    dep.status = new


def claim_status(db: Session, dep: Deployment, new: Status) -> None:
    """Move ``dep`` to ``new`` only if nobody changed its status since we read it."""
    check_transition(dep.status, new)
    result = db.execute(
        update(Deployment)
        .where(Deployment.id == dep.id, Deployment.status == dep.status)
        .values(status=new, updated_at=utcnow())
    )
    if result.rowcount != 1:
        db.rollback()
        raise DeploymentError("This deployment is busy; wait for the current step to finish")
    set_committed_value(dep, "status", new.value)


def build_context(
    svc: AppServices,
    dep: Deployment,
    entry: WorkflowEntry,
    *,
    refs: dict[str, Any] | None = None,
    user_step_state: str | None = None,
    previous_refs: dict[str, Any] | None = None,
) -> DeployContext:
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
        user_step_state=user_step_state,
        callback_url=f"{svc.settings.base_url}/make/callback?state={user_step_state}"
        if user_step_state
        else None,
        credentials=UserCredentials(svc, dep.user),
        previous_refs=dict(previous_refs or {}),
    )


def _queue_job(
    svc: AppServices, db: Session, dep: Deployment, kind: str, payload: dict[str, Any] | None = None
) -> None:
    job = Job(deployment_id=dep.id, kind=kind, payload=payload or {})
    db.add(job)
    db.commit()
    svc.runner.submit(job.id)
    db.refresh(dep)


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
    if entry.platform is Platform.N8N:
        reject_expressions(cleaned)
    missing = missing_connectors(svc, entry, active_connectors(user))
    if missing:
        names = ", ".join(svc.catalog.connectors[m].name for m in missing)
        raise DeploymentError(f"Connect first: {names}")

    dep = get_deployment(db, user, workflow_id)
    if dep is None:
        dep = Deployment(user_id=user.id, workflow_id=workflow_id, status=Status.DEPLOYING)
        db.add(dep)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise DeploymentError("Another deploy request is in progress") from None
        kind = "deploy"
    elif dep.status in BUSY:
        raise DeploymentError("This deployment is busy; wait for the current step to finish")
    elif dep.status == Status.STOPPED:
        claim_status(db, dep, Status.DEPLOYING)
        kind = "deploy"
    else:
        claim_status(db, dep, Status.REDEPLOYING)
        kind = "redeploy"
    dep.error = None
    add_event(dep, "requested", "Deploy requested" if kind == "deploy" else "Redeploy requested")
    # The new settings travel with the job: a redeploy must remove the old resources with the
    # settings they were created with.
    _queue_job(svc, db, dep, kind, {"settings": cleaned})
    return dep


def request_delete(
    svc: AppServices, db: Session, user: User, workflow_id: str, *, reason: str = "Delete requested"
) -> Deployment:
    workflow_entry(svc, workflow_id)
    dep = get_deployment(db, user, workflow_id)
    if dep is None:
        raise DeploymentError("Not deployed", 404)
    if dep.status == Status.STOPPED:
        return dep
    if dep.status in BUSY:
        raise DeploymentError("This deployment is busy; wait for the current step to finish")
    claim_status(db, dep, Status.STOPPING)
    add_event(dep, "requested", reason)
    _queue_job(svc, db, dep, "undeploy")
    return dep


def request_expire(svc: AppServices, db: Session, dep: Deployment) -> bool:
    """Stop a deployment that outlived the demo time limit. Returns False if it was busy."""
    if dep.status in BUSY or dep.status == Status.STOPPED:
        return False
    try:
        claim_status(db, dep, Status.STOPPING)
    except DeploymentError:
        return False
    add_event(dep, "expiring", "The demo time limit was reached")
    _queue_job(svc, db, dep, "expire")
    return True


def finish_user_step(
    svc: AppServices, db: Session, state: dict[str, Any], params: dict[str, str]
) -> Deployment:
    """Called when the user comes back from the platform's popup (Make Bridge).

    Claims the deployment (so a repeated redirect can't finish it twice) and queues a job that
    completes the deploy on the platform; the popup page answers right away."""
    dep = db.get(Deployment, int(state.get("deployment_id", 0)))
    if dep is None:
        raise DeploymentError("Unknown deployment", 404)
    nonce = (dep.platform_refs or {}).get(NONCE_REF)
    if not nonce or not secrets.compare_digest(str(state.get("nonce", "")), nonce):
        raise DeploymentError("This link is from an earlier deploy; use the latest popup")
    if dep.status == Status.DEPLOYING:
        return dep  # the same popup came back twice; the first callback is already finishing
    if dep.status != Status.AWAITING_USER:
        raise DeploymentError("This deployment isn't waiting for you")
    claim_status(db, dep, Status.DEPLOYING)
    add_event(dep, "finishing", "You finished in the platform's popup; completing the deploy")
    _queue_job(svc, db, dep, "finish", {"params": dict(params)})
    return dep


def run_now(svc: AppServices, db: Session, user: User, workflow_id: str) -> RunStarted:
    entry = workflow_entry(svc, workflow_id)
    if not entry.run_now:
        raise DeploymentError("This workflow can't be started from the demo", 400)
    dep = get_deployment(db, user, workflow_id)
    if dep is None or dep.status != Status.ACTIVE:
        raise DeploymentError("Deploy the workflow first")
    try:
        started = svc.registry.get(entry.platform).run_now(build_context(svc, dep, entry))
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
        return svc.registry.get(entry.platform).recent_runs(build_context(svc, dep, entry))
    except AdapterError as exc:
        raise DeploymentError(str(exc), 502) from None


# ------------------------------------------------------------------------- background jobs


def run_job(svc: AppServices, job_id: int) -> None:
    with svc.db.session() as db:
        claimed = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running", started_at=utcnow())
        ).rowcount
        db.commit()
        if claimed != 1:
            return
        job = db.get(Job, job_id)
        dep: Deployment | None = None
        try:
            dep = db.get(Deployment, job.deployment_id)
            if dep is None:
                raise _SkipJob("deployment no longer exists")
            if dep.status != JOB_EXPECTS[job.kind]:
                raise _SkipJob(f"deployment is {dep.status}, expected {JOB_EXPECTS[job.kind]}")
            _execute(svc, db, job, dep)
            job.status = "succeeded"
        except _SkipJob as exc:
            job.status, job.error = "failed", f"skipped: {exc}"
        except AdapterError as exc:
            _fail(dep, str(exc))
            job.status, job.error = "failed", str(exc)
        except Exception as exc:  # noqa: BLE001 - surface any failure on the deployment
            log.exception("job %s failed", job_id)
            if dep is not None:
                _fail(dep, f"Unexpected error: {exc.__class__.__name__}")
            job.status, job.error = "failed", repr(exc)
        finally:
            job.finished_at = utcnow()
            db.commit()


def _execute(svc: AppServices, db: Session, job: Job, dep: Deployment) -> None:
    entry = svc.catalog.workflow(dep.workflow_id)
    adapter = svc.registry.get(entry.platform)
    previous_refs = dict(dep.platform_refs or {})
    if job.kind in ("redeploy", "undeploy", "expire") and previous_refs:
        adapter.undeploy(build_context(svc, dep, entry))  # old settings + old refs
        dep.platform_refs = {}
        add_event(dep, "removed", "Removed the previous deployment from the platform")
    if job.kind == "finish":
        params = {str(k): str(v) for k, v in ((job.payload or {}).get("params") or {}).items()}
        result = adapter.finish_user_step(build_context(svc, dep, entry), params)
        _apply_result(svc, dep, result, nonce=None)
        return
    if job.kind in ("deploy", "redeploy"):
        dep.inputs = dict((job.payload or {}).get("settings", {}))
        nonce = secrets.token_urlsafe(16)
        state = svc.signer.dumps({"deployment_id": dep.id, "nonce": nonce}, USER_STEP_PURPOSE)
        context = build_context(svc, dep, entry, refs={}, user_step_state=state, previous_refs=previous_refs)
        result = adapter.deploy(context)
        _apply_result(svc, dep, result, nonce=nonce)
        return
    set_status(dep, Status.STOPPED)
    dep.expires_at = None
    if job.kind == "expire":
        add_event(dep, "expired", "Stopped automatically after the demo time limit")
    else:
        add_event(dep, "stopped", "Deployment deleted")


def recover_stale_jobs(svc: AppServices, older_than: timedelta) -> int:
    """Fail queued/running jobs older than ``older_than`` (e.g. lost in a restart)."""
    cutoff = utcnow() - older_than
    recovered = 0
    with svc.db.session() as db:
        jobs = db.scalars(
            select(Job).where(Job.status.in_(("queued", "running")), Job.created_at <= cutoff)
        ).all()
        for job in jobs:
            job.status, job.error, job.finished_at = "failed", "interrupted", utcnow()
            dep = db.get(Deployment, job.deployment_id)
            if dep is not None and dep.status == JOB_EXPECTS.get(job.kind):
                _fail(dep, "Interrupted before it finished; try again")
            recovered += 1
        db.commit()
    if recovered:
        log.warning("recovered %d interrupted job(s)", recovered)
    return recovered


def _apply_result(svc: AppServices, dep: Deployment, result: DeployResult, *, nonce: str | None) -> None:
    refs = {k: v for k, v in result.refs.items() if k != NONCE_REF}
    if result.status == "awaiting_user":
        if nonce is None:
            raise AdapterError("The platform asked for another popup step; deploy again")
        dep.platform_refs = {**refs, NONCE_REF: nonce}
        set_status(dep, Status.AWAITING_USER)
        add_event(dep, "awaiting_user", result.message or "Waiting for you to finish on the platform")
        return
    dep.platform_refs = refs
    set_status(dep, Status.ACTIVE)
    now = utcnow()
    dep.deployed_at = now
    dep.expires_at = now + timedelta(hours=svc.settings.deployment_ttl_hours)
    add_event(dep, "active", result.message or "Deployed")


def _fail(dep: Deployment | None, message: str) -> None:
    if dep is None:
        return
    if dep.status not in (*BUSY, Status.AWAITING_USER):
        log.error("not marking deployment %s failed from %s: %s", dep.id, dep.status, message)
        return
    set_status(dep, Status.FAILED)
    dep.error = message
    add_event(dep, "failed", message)
