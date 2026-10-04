"""The shared Slack bot's view of the demo: who is activated, and the cards it creates."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from workflow_demo.db import Deployment, utcnow
from workflow_demo.services.container import AppServices
from workflow_demo.services.deployments import add_event
from workflow_demo.services.states import Status

MAX_RUNS = 20
MAX_TITLE = 200


def _bot_workflows(svc: AppServices) -> list[str]:
    return [e.id for e in svc.catalog.workflows if e.modal and e.modal.shared_deployment]


def activation(svc: AppServices, db: Session, slack_user_id: str, *, lock: bool = False) -> Deployment | None:
    """The most recent live activation for this Slack user (if several demo users share one).

    Live = active and not past its expiry time, even before the sweeper marks it expired."""
    query = (
        select(Deployment)
        .where(
            Deployment.workflow_id.in_(_bot_workflows(svc)),
            Deployment.status == Status.ACTIVE,
            or_(Deployment.expires_at.is_(None), Deployment.expires_at > utcnow()),
        )
        .order_by(Deployment.deployed_at.desc())
    )
    if lock:
        query = query.with_for_update()
    for dep in db.scalars(query):
        if (dep.platform_refs or {}).get("slack_user_id") == slack_user_id:
            return dep
    return None


def user_key(svc: AppServices, db: Session, slack_user_id: str) -> str | None:
    """The tester's current Meegle user key, while their activation and connections still hold.

    Disconnecting Slack or Meegle (or reconnecting Slack as someone else) ends the mapping at once;
    a corrected user key applies without activating again."""
    dep = activation(svc, db, slack_user_id)
    if dep is None:
        return None
    connections = {c.connector: c for c in dep.user.connections if c.status == "active"}
    slack, key = connections.get("slack"), connections.get("meegle_user_key")
    if slack is None or (slack.details or {}).get("slack_user_id") != slack_user_id or key is None:
        return None
    return (key.details or {}).get("value") or None


def record_card(svc: AppServices, db: Session, slack_user_id: str, title: str, url: str) -> bool:
    """Show a card the bot created under the tester's results. False if they aren't activated."""
    dep = activation(svc, db, slack_user_id, lock=True)
    if dep is None:
        db.rollback()
        return False
    if len(title) > MAX_TITLE:
        title = title[: MAX_TITLE - 1] + "…"
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
