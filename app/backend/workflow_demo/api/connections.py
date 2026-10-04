"""Connections list/remove. Real connect flows (Nango, manual secrets) arrive in P2; in fake mode
``POST /api/connections/{connector}/fake`` marks a connector as connected."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from workflow_demo.api.deps import DB, CurrentUser, Services
from workflow_demo.api.schemas import ConnectionOut
from workflow_demo.catalog.models import ConnectorKind
from workflow_demo.db import Connection, User

router = APIRouter(prefix="/api/connections", tags=["connections"])


def connection_out(svc, c: Connection) -> ConnectionOut:
    return ConnectionOut(
        connector=c.connector,
        name=svc.catalog.connectors[c.connector].name,
        method=c.method,
        status=c.status,
        details=c.details or {},
        updated_at=c.updated_at,
    )


def _connector(svc, connector_id: str):
    connector = svc.catalog.connectors.get(connector_id)
    if connector is None:
        raise HTTPException(404, "Unknown connector")
    if connector.kind is ConnectorKind.PLATFORM_POPUP:
        raise HTTPException(400, "This account is connected inside the platform's popup")
    return connector


def _get(db, user: User, connector_id: str) -> Connection | None:
    return db.scalar(
        select(Connection).where(Connection.user_id == user.id, Connection.connector == connector_id)
    )


@router.get("", response_model=list[ConnectionOut])
def list_connections(svc: Services, db: DB, user: CurrentUser) -> list[ConnectionOut]:
    return [connection_out(svc, c) for c in user.connections if c.connector in svc.catalog.connectors]


@router.delete("/{connector_id}", status_code=204)
def delete_connection(connector_id: str, svc: Services, db: DB, user: CurrentUser) -> None:
    _connector(svc, connector_id)
    existing = _get(db, user, connector_id)
    if existing is not None:
        db.delete(existing)
        db.commit()


@router.post("/{connector_id}/fake", response_model=ConnectionOut)
def fake_connect(connector_id: str, svc: Services, db: DB, user: CurrentUser) -> ConnectionOut:
    if not svc.settings.fake_platforms:
        raise HTTPException(404, "Not available")
    _connector(svc, connector_id)
    existing = _get(db, user, connector_id) or Connection(
        user_id=user.id, connector=connector_id, method="fake"
    )
    existing.method = "fake"
    existing.status = "active"
    existing.details = {"label": f"{user.username} (fake {connector_id})"}
    db.add(existing)
    db.commit()
    return connection_out(svc, existing)
