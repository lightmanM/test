"""The shared Slack bot's view of the demo: who is activated, and the cards it creates."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from workflow_demo.db import Deployment, utcnow
from workflow_demo.services.container import AppServices
from workflow_demo.services.deployments import add_event
from workflow_demo.services.states import Status

MAX_RUNS = 20


def _bot_workflows(svc: AppServices) -> list[str]:
    return [e.id for e in svc.catalog.workflows if e.modal and e.modal.shared_deployment]


def activation(svc: AppServices, db: Session, slack_user_id: str, *, lock: bool = False) -> Deployment | None:
    """The most recent active activation for this Slack user (if several demo users share one)."""
    query = (
        select(Deployment)
        .where(Deployment.workflow_id.in_(_bot_workflows(svc)), Deployment.status == Status.ACTIVE)
        .order_by(Deployment.deployed_at.desc())
    )
    if lock:
        query = query.with_for_update()
    for dep in db.scalars(query):
        if (dep.platform_refs or {}).get("slack_user_id") == slack_user_id:
            return dep
    return None


def user_key(svc: AppServices, db: Session, slack_user_id: str) -> str | None:
    dep = activation(svc, db, slack_user_id)
    return (dep.platform_refs or {}).get("meegle_user_key") if dep is not None else None


def record_card(svc: AppServices, db: Session, slack_user_id: str, title: str, url: str) -> bool:
    """Show a card the bot created under the tester's results. False if they aren't activated."""
    dep = activation(svc, db, slack_user_id, lock=True)
    if dep is None:
        db.rollback()
        return False
    now = utcnow().isoformat()
    run: dict[str, Any] = {
        "id": f"card-{uuid.uuid4().hex[:12]}",
        "status": "success",
        "started_at": now,
        "finished_at": now,
        "summary": f"Created card “{title}” — {url}",
    }
    refs = dict(dep.platform_refs or {})
    refs["runs"] = [run, *(refs.get("runs") or [])][:MAX_RUNS]
    dep.platform_refs = refs
    add_event(dep, "card_created", f"The bot created card “{title}”")
    db.commit()
    return True
