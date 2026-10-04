"""Periodic housekeeping: the 24 h limit, abandoned popups, lost jobs, platform orphans.

``sweep()`` runs every ``SWEEP_INTERVAL_SECONDS`` in the web process (and can be triggered from the
admin page); a scheduled function can call it too when the app scales to zero.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select

from workflow_demo.adapters.base import AdapterError, DeploymentSnapshot
from workflow_demo.catalog.models import Platform
from workflow_demo.db import Deployment, utcnow
from workflow_demo.services.container import AppServices
from workflow_demo.services.deployments import recover_stale_jobs, request_expire
from workflow_demo.services.states import Status

log = logging.getLogger(__name__)

ABANDONED_POPUP = timedelta(hours=1)  # awaiting_user this long → stop it
STALE_JOB = timedelta(minutes=30)  # a queued/running job this old was lost
ORPHAN_AGE = timedelta(hours=1)  # platform items younger than this may belong to an in-flight deploy


@dataclass
class SweepReport:
    stopped: list[str] = field(default_factory=list)
    recovered_jobs: int = 0
    orphans_removed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def expiry_reason(dep: Deployment, now) -> str | None:
    if dep.status in (Status.ACTIVE, Status.FAILED) and dep.expires_at is not None and dep.expires_at <= now:
        return "time limit reached"
    if dep.status == Status.AWAITING_USER and dep.updated_at <= now - ABANDONED_POPUP:
        return "platform popup not finished"
    return None


def sweep(svc: AppServices) -> SweepReport:
    report = SweepReport()
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
            if reason and request_expire(svc, db, dep):
                report.stopped.append(f"{dep.user.username} / {dep.workflow_id}: {reason}")
        snapshots = [
            DeploymentSnapshot(
                username=d.user.username,
                workflow=svc.catalog.workflow(d.workflow_id),
                status=d.status,
                refs=dict(d.platform_refs or {}),
            )
            for d in db.scalars(select(Deployment)).all()
            if d.workflow_id in {w.id for w in svc.catalog.workflows}
        ]
    for platform in Platform:
        try:
            adapter = svc.registry.get(platform)
        except AdapterError:
            continue
        sweep_orphans = getattr(adapter, "sweep_orphans", None)
        if sweep_orphans is None:
            continue
        try:
            report.orphans_removed += sweep_orphans(snapshots, now - ORPHAN_AGE)
        except Exception as exc:  # noqa: BLE001 - one platform's trouble mustn't stop the sweep
            log.warning("orphan sweep for %s failed", platform.value, exc_info=True)
            report.errors.append(f"{platform.value}: {exc}")
    if report.stopped or report.recovered_jobs or report.orphans_removed or report.errors:
        log.info("sweep: %s", report)
    return report


class Sweeper:
    """Runs ``sweep()`` on an interval in a daemon thread until stopped."""

    def __init__(self, svc: AppServices, interval_seconds: float) -> None:
        self._svc = svc
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="sweeper", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                sweep(self._svc)
            except Exception:  # noqa: BLE001 - keep sweeping on the next interval
                log.exception("sweep failed")
