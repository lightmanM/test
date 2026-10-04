"""Connecting accounts: Nango OAuth popups (Slack, Google) and manual values (Meegle)."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from workflow_demo.catalog.models import Connector, ConnectorKind
from workflow_demo.crypto import CryptoError
from workflow_demo.db import Connection, User
from workflow_demo.nango import NangoConnection, NangoError
from workflow_demo.services.container import AppServices

log = logging.getLogger(__name__)

# Per-connector checks for values typed into the demo.
MANUAL_RULES: dict[str, tuple[re.Pattern[str], str]] = {
    "meegle_mcp_token": (re.compile(r"^\S{8,500}$"), "Paste the whole token (no spaces)"),
    "meegle_user_key": (re.compile(r"^[A-Za-z0-9_-]{3,64}$"), "A user key has 3-64 letters, digits, - or _"),
}
FAKE_CHANNELS = [{"id": "C0FAKE0001", "name": "general"}, {"id": "C0FAKE0002", "name": "demo-alerts"}]


class ConnectionError_(Exception):  # noqa: N801 - avoid shadowing the builtin ConnectionError
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def connector(svc: AppServices, connector_id: str) -> Connector:
    found = svc.catalog.connectors.get(connector_id)
    if found is None:
        raise ConnectionError_("Unknown connector", 404)
    if found.kind is ConnectorKind.PLATFORM_POPUP:
        raise ConnectionError_("This account is connected inside the platform's popup")
    return found


def get_connection(db: Session, user: User, connector_id: str) -> Connection | None:
    return db.scalar(
        select(Connection).where(Connection.user_id == user.id, Connection.connector == connector_id)
    )


def _secret_context(user: User, connector_id: str) -> str:
    return f"user:{user.id}:connector:{connector_id}"


def _nango(svc: AppServices):
    if svc.nango is None:
        raise ConnectionError_("Account connections aren't configured on this server", 503)
    return svc.nango


# ----------------------------------------------------------------------------- Nango


def start_session(svc: AppServices, user: User, connector_id: str) -> dict[str, Any]:
    found = connector(svc, connector_id)
    if found.kind is not ConnectorKind.NANGO:
        raise ConnectionError_("This connector is entered as text, not through a popup")
    try:
        session = _nango(svc).create_connect_session(
            found.integration, tags={"end_user_id": user.username, "connector": connector_id}
        )
    except NangoError as exc:
        raise ConnectionError_(str(exc), 502) from None
    return {"token": session.token, "expires_at": session.expires_at, "integration": found.integration}


def complete_session(
    svc: AppServices, db: Session, user: User, connector_id: str, connection_id: str
) -> Connection:
    """Store the connection Nango created, after checking it really belongs to this user."""
    found = connector(svc, connector_id)
    if found.kind is not ConnectorKind.NANGO:
        raise ConnectionError_("This connector is entered as text, not through a popup")
    nango = _nango(svc)
    try:
        conn = nango.get_connection(connection_id, found.integration)
    except NangoError as exc:
        raise ConnectionError_(str(exc), 404 if exc.status_code == 404 else 502) from None
    if conn.tags.get("end_user_id") != user.username or conn.provider_config_key != found.integration:
        raise ConnectionError_("That connection belongs to someone else", 403)

    details = describe(svc, connector_id, conn)
    existing = get_connection(db, user, connector_id)
    if existing is not None and existing.method == "nango" and existing.nango_connection_id != connection_id:
        _delete_in_nango(svc, existing)
    record = existing or Connection(user_id=user.id, connector=connector_id)
    record.method = "nango"
    record.nango_integration = found.integration
    record.nango_connection_id = connection_id
    record.secret_ciphertext = None
    record.details = details
    record.status = "active"
    db.add(record)
    db.commit()
    return record


def describe(svc: AppServices, connector_id: str, conn: NangoConnection) -> dict[str, Any]:
    """Non-secret details shown to the user and used by deploys (never tokens)."""
    raw = conn.raw
    if connector_id == "slack":
        team = raw.get("team") or {}
        return {
            "label": f"Slack · {team.get('name') or 'workspace'}",
            "team_id": team.get("id"),
            "team_name": team.get("name"),
            "slack_user_id": (raw.get("authed_user") or {}).get("id"),
            "bot_user_id": raw.get("bot_user_id"),
        }
    if connector_id == "google":
        email = _google_email(svc, conn.access_token)
        return {"label": email or "Google account", "email": email}
    return {"label": conn.provider or connector_id}


def _google_email(svc: AppServices, access_token: str | None) -> str | None:
    if not access_token:
        return None
    try:
        resp = svc.http.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        return resp.json().get("email") if resp.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


def fresh_credentials(svc: AppServices, record: Connection) -> NangoConnection:
    """The connection with an access token Nango refreshed if needed (used by deploys)."""
    try:
        return _nango(svc).get_connection(
            record.nango_connection_id, record.nango_integration, refresh_token=True
        )
    except NangoError as exc:
        raise ConnectionError_(f"Couldn't read the {record.connector} connection: {exc}", 502) from None


def _delete_in_nango(svc: AppServices, record: Connection) -> None:
    if svc.nango is None or not record.nango_connection_id:
        return
    try:
        svc.nango.delete_connection(record.nango_connection_id, record.nango_integration)
    except NangoError:
        log.warning("couldn't delete Nango connection %s", record.nango_connection_id, exc_info=True)


# ----------------------------------------------------------------------------- manual values


def save_manual(svc: AppServices, db: Session, user: User, connector_id: str, value: str) -> Connection:
    found = connector(svc, connector_id)
    if found.kind is not ConnectorKind.MANUAL:
        raise ConnectionError_("This connector is connected through a popup")
    value = value.strip()
    pattern, message = MANUAL_RULES.get(connector_id, (re.compile(r"^.{1,500}$"), "Enter a value"))
    if not pattern.match(value):
        raise ConnectionError_(message, 422)

    record = get_connection(db, user, connector_id) or Connection(user_id=user.id, connector=connector_id)
    if record.method == "nango":
        _delete_in_nango(svc, record)
    record.method = "manual"
    record.nango_integration = record.nango_connection_id = None
    if found.secret:
        if svc.secret_box is None:
            raise ConnectionError_("Secret storage isn't configured on this server", 503)
        record.secret_ciphertext = svc.secret_box.encrypt(value, _secret_context(user, connector_id))
        record.details = {"label": f"saved · ends with {value[-4:]}"}
    else:
        record.secret_ciphertext = None
        record.details = {"label": value, "value": value}
    record.status = "active"
    db.add(record)
    db.commit()
    return record


def read_secret(svc: AppServices, user: User, record: Connection) -> str:
    """Decrypt a manual secret (only inside deploy jobs)."""
    if record.secret_ciphertext is None:
        value = (record.details or {}).get("value")
        if value is None:
            raise ConnectionError_(f"No value stored for {record.connector}")
        return value
    if svc.secret_box is None:
        raise ConnectionError_("Secret storage isn't configured on this server", 503)
    try:
        return svc.secret_box.decrypt(record.secret_ciphertext, _secret_context(user, record.connector))
    except CryptoError:
        raise ConnectionError_(f"The saved {record.connector} value can't be read; enter it again") from None


# ----------------------------------------------------------------------------- shared


def delete(svc: AppServices, db: Session, user: User, connector_id: str) -> None:
    connector(svc, connector_id)
    record = get_connection(db, user, connector_id)
    if record is None:
        return
    if record.method == "nango":
        _delete_in_nango(svc, record)
    db.delete(record)
    db.commit()


def slack_channels(svc: AppServices, db: Session, user: User) -> list[dict[str, str]]:
    record = get_connection(db, user, "slack")
    if record is None or record.status != "active":
        raise ConnectionError_("Connect Slack first", 409)
    if record.method == "fake":
        return FAKE_CHANNELS
    token = fresh_credentials(svc, record).access_token
    channels: list[dict[str, str]] = []
    cursor = ""
    for _ in range(5):  # up to 1,000 channels
        try:
            resp = svc.http.get(
                "https://slack.com/api/conversations.list",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "exclude_archived": "true",
                    "types": "public_channel",
                    "limit": 200,
                    "cursor": cursor,
                },
            )
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            raise ConnectionError_("Slack is unreachable", 502) from None
        if not data.get("ok"):
            raise ConnectionError_(f"Slack error: {data.get('error', 'unknown')}", 502)
        channels += [{"id": c["id"], "name": c["name"]} for c in data.get("channels", [])]
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
    return sorted(channels, key=lambda c: c["name"])
