"""Connect, list and remove account connections; Slack channel picker."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from workflow_demo.api.deps import DB, CurrentUser, Services
from workflow_demo.api.schemas import ConnectionOut
from workflow_demo.db import Connection
from workflow_demo.services import connections as svc_connections
from workflow_demo.services.connections import ConnectionError_
from workflow_demo.services.container import AppServices

router = APIRouter(tags=["connections"])


class SessionOut(BaseModel):
    token: str
    expires_at: str
    integration: str
    api_url: str  # where the Connect UI reaches Nango (NANGO_HOST)
    connect_url: str  # where the Connect UI itself is served


class CompleteRequest(BaseModel):
    # Nango connection IDs are UUIDs; anything path-like is refused before reaching Nango.
    connection_id: str = Field(max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]*$")


class SecretRequest(BaseModel):
    value: str = Field(max_length=1000)


class Channel(BaseModel):
    id: str
    name: str


def connection_out(svc: AppServices, c: Connection) -> ConnectionOut:
    details = {k: v for k, v in (c.details or {}).items() if v is not None}
    return ConnectionOut(
        connector=c.connector,
        name=svc.catalog.connectors[c.connector].name,
        method=c.method,
        status=c.status,
        details=details,
        updated_at=c.updated_at,
    )


def _raise(exc: ConnectionError_) -> None:
    raise HTTPException(exc.status_code, exc.message) from None


@router.get("/api/connections", response_model=list[ConnectionOut])
def list_connections(svc: Services, db: DB, user: CurrentUser) -> list[ConnectionOut]:
    return [connection_out(svc, c) for c in user.connections if c.connector in svc.catalog.connectors]


@router.post("/api/connections/{connector_id}/session", response_model=SessionOut)
def start_session(connector_id: str, svc: Services, user: CurrentUser) -> SessionOut:
    try:
        return SessionOut(**svc_connections.start_session(svc, user, connector_id))
    except ConnectionError_ as exc:
        _raise(exc)


@router.post("/api/connections/{connector_id}/complete", response_model=ConnectionOut)
def complete_session(
    connector_id: str, body: CompleteRequest, svc: Services, db: DB, user: CurrentUser
) -> ConnectionOut:
    try:
        record = svc_connections.complete_session(svc, db, user, connector_id, body.connection_id)
    except ConnectionError_ as exc:
        _raise(exc)
    return connection_out(svc, record)


@router.put("/api/connections/{connector_id}/secret", response_model=ConnectionOut)
def save_manual(
    connector_id: str, body: SecretRequest, svc: Services, db: DB, user: CurrentUser
) -> ConnectionOut:
    try:
        record = svc_connections.save_manual(svc, db, user, connector_id, body.value)
    except ConnectionError_ as exc:
        _raise(exc)
    return connection_out(svc, record)


@router.delete("/api/connections/{connector_id}", status_code=204)
def delete_connection(connector_id: str, svc: Services, db: DB, user: CurrentUser) -> None:
    try:
        svc_connections.delete(svc, db, user, connector_id)
    except ConnectionError_ as exc:
        _raise(exc)


@router.post("/api/connections/{connector_id}/fake", response_model=ConnectionOut)
def fake_connect(connector_id: str, svc: Services, db: DB, user: CurrentUser) -> ConnectionOut:
    """Fake-platform mode only: mark an account as connected with demo data."""
    if not svc.settings.fake_platforms:
        raise HTTPException(404, "Not available")
    try:
        record = svc_connections.save_fake(svc, db, user, connector_id)
    except ConnectionError_ as exc:
        _raise(exc)
    return connection_out(svc, record)


@router.get("/api/slack/channels", response_model=list[Channel])
def slack_channels(svc: Services, db: DB, user: CurrentUser) -> list[Channel]:
    try:
        return [Channel(**c) for c in svc_connections.slack_channels(svc, db, user)]
    except ConnectionError_ as exc:
        _raise(exc)
