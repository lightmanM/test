"""Periodic housekeeping: the 24 h limit, abandoned popups, lost jobs, platform orphans.

``sweep()`` runs every ``SWEEP_INTERVAL_SECONDS`` in the web process (and can be triggered from the
admin page); a scheduled function can call it too when the app scales to zero.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from workflow_demo.adapters.base import AdapterError, DeploymentSnapshot, OrphanReport
from workflow_demo.catalog.models import Platform
from workflow_demo.db import Deployment, User, utcnow
from workflow_demo.services.container import AppServices
from workflow_demo.services.deployments import TIME_LIMIT, recover_stale_jobs, request_expire
from workflow_demo.services.states import Status

log = logging.getLogger(__name__)

ABANDONED_POPUP = timedelta(hours=1)  # awaiting_user this long → stop it
STALE_JOB = timedelta(minutes=30)  # a queued/running job this old was lost
ORPHAN_AGE = timedelta(hours=1)  # platform items younger than this may belong to an in-flight deploy
POPUP_ABANDONED = (
    "The platform popup wasn't finished within an hour",
    "Stopped because the platform popup wasn't finished",
)


@dataclass
class SweepReport:
    stopped: list[str] = field(default_factory=list)
    recovered_jobs: int = 0
    orphans_removed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    orphan_sweep: bool = False  # whether platform orphans were looked for (ORPHAN_SWEEP)


def expiry_reason(dep: Deployment, now: datetime) -> tuple[str, str] | None:
    if dep.status in (Status.ACTIVE, Status.FAILED) and dep.expires_at is not None and dep.expires_at <= now:
        return TIME_LIMIT
    if dep.status == Status.AWAITING_USER and dep.updated_at <= now - ABANDONED_POPUP:
        return POPUP_ABANDONED
    return None


def _snapshots(svc: AppServices, db: Session, username: str | None = None) -> list[DeploymentSnapshot]:
    query = select(Deployment)
    if username is not None:
        query = query.join(User).where(User.username == username)
    catalog = {w.id: w for w in svc.catalog.workflows}
    return [
        DeploymentSnapshot(
            username=d.user.username,
            workflow_id=d.workflow_id,
            workflow=catalog.get(d.workflow_id),  # unknown workflows still protect their refs
            status=d.status,
            refs=dict(d.platform_refs or {}),
            updated_at=d.updated_at,
        )
        for d in db.scalars(query).all()
    ]


def sweep(svc: AppServices) -> SweepReport:
    report = SweepReport(orphan_sweep=svc.settings.orphan_sweep)
    report.recovered_jobs = recover_stale_jobs(svc, older_than=STALE_JOB)
    now = utcnow()
    with svc.db.session() as db:
        candidates = db.scalars(
            select(Deployment).where(
                Deployment.status.in_((Status.ACTIVE, Status.FAILED, Status.AWAITING_USER))
            )
        ).all()
        for dep in candidates:
            reason = expiry_reason(dep, now)
            if reason and request_expire(svc, db, dep, reason):
                report.stopped.append(f"{dep.user.username} / {dep.workflow_id}: {reason[0]}")
        snapshots = _snapshots(svc, db)
    if svc.settings.orphan_sweep:
        _sweep_orphans(svc, snapshots, now - ORPHAN_AGE, report)
    if report.stopped or report.recovered_jobs or report.orphans_removed or report.errors:
        log.info("sweep: %s", report)
    return report


def _sweep_orphans(
    svc: AppServices, snapshots: list[DeploymentSnapshot], older_than: datetime, report: SweepReport
) -> None:
    def current(username: str) -> list[DeploymentSnapshot]:
        with svc.db.session() as db:
            return _snapshots(svc, db, username)

    for platform in Platform:
        try:
            adapter = svc.registry.get(platform)
        except AdapterError:
            continue
        sweep_orphans = getattr(adapter, "sweep_orphans", None)
        if sweep_orphans is None:
            continue
        try:
            result: OrphanReport = sweep_orphans(snapshots, older_than, current=current)
        except Exception as exc:  # noqa: BLE001 - one platform's trouble mustn't stop the sweep
            log.warning("orphan sweep for %s failed", platform.value, exc_info=True)
            report.errors.append(f"{platform.value}: {exc}")
            continue
        report.orphans_removed += result.removed
        report.errors += result.errors


class Sweeper:
    """Runs ``sweep()`` on an interval in a daemon thread until stopped."""

    def __init__(self, svc: AppServices, interval_seconds: float) -> None:
        self._svc = svc
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="sweeper", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 30) -> None:
        """Stop and wait for a sweep in progress (it uses the HTTP client closed after this)."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                sweep(self._svc)
            except Exception:  # noqa: BLE001 - keep sweeping on the next interval
                log.exception("sweep failed")
