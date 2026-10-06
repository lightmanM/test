"""Connecting accounts: Nango OAuth popups (Slack, Google) and manual values (Meegle)."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from workflow_demo import google
from workflow_demo.adapters.base import AdapterError, OAuthTokens
from workflow_demo.catalog.models import Connector, ConnectorKind
from workflow_demo.crypto import CryptoError
from workflow_demo.db import Connection, User
from workflow_demo.google import GoogleApi
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


def _store(
    svc: AppServices, db: Session, user: User, connector_id: str, update: Callable[[Connection], None]
) -> Connection:
    """Create or update the user's row for a connector, then delete the Nango connection it replaced.

    The old Nango connection goes only after the new row is committed, so a failed save never leaves
    the row pointing at a deleted connection. Two concurrent first saves race on the unique
    (user, connector) constraint; the loser retries once as an update.
    """
    for attempt in range(2):
        record = get_connection(db, user, connector_id)
        replaced = _nango_ref(record)
        record = record or Connection(user_id=user.id, connector=connector_id)
        update(record)
        record.status = "active"
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if attempt:
                raise
            continue
        if replaced and replaced != _nango_ref(record):
            _delete_in_nango(svc, *replaced)
        return record
    raise AssertionError("unreachable")


def _nango_ref(record: Connection | None) -> tuple[str | None, str] | None:
    if record is None or record.method != "nango" or not record.nango_connection_id:
        return None
    return record.nango_integration, record.nango_connection_id


def _delete_in_nango(svc: AppServices, integration: str | None, connection_id: str) -> None:
    if svc.nango is None or not integration:
        return
    try:
        svc.nango.delete_connection(connection_id, integration)
    except NangoError:
        log.warning("couldn't delete Nango connection %s", connection_id, exc_info=True)


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
    return {
        "token": session.token,
        "expires_at": session.expires_at,
        "integration": found.integration,
        "api_url": svc.settings.nango_host.rstrip("/"),
        "connect_url": svc.settings.nango_connect_url.rstrip("/"),
    }


def complete_session(
    svc: AppServices, db: Session, user: User, connector_id: str, connection_id: str
) -> Connection:
    """Store the connection Nango created, after checking it really belongs to this user."""
    found = connector(svc, connector_id)
    if found.kind is not ConnectorKind.NANGO:
        raise ConnectionError_("This connector is entered as text, not through a popup")
    try:
        conn = _nango(svc).get_connection(connection_id, found.integration)
    except NangoError as exc:
        raise ConnectionError_(str(exc), 404 if exc.status_code == 404 else 502) from None
    if conn.tags.get("end_user_id") != user.username or conn.provider_config_key != found.integration:
        raise ConnectionError_("That connection belongs to someone else", 403)
    details = describe(svc, connector_id, conn)

    def update(record: Connection) -> None:
        record.method = "nango"
        record.nango_integration = found.integration
        record.nango_connection_id = connection_id
        record.secret_ciphertext = None
        record.details = details

    return _store(svc, db, user, connector_id, update)


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
        # Through Nango's proxy: Google tokens are never read out of Nango.
        email = google.user_email(GoogleApi(_nango(svc), conn.connection_id, conn.provider_config_key))
        return {"label": email or "Google account", "email": email}
    return {"label": conn.provider or connector_id}


def google_api(svc: AppServices, record: Connection) -> GoogleApi:
    """Google calls for this connection, through Nango's proxy."""
    if record.method != "nango" or not record.nango_connection_id or not record.nango_integration:
        raise ConnectionError_(f"{record.connector} isn't connected through Nango")
    return GoogleApi(_nango(svc), record.nango_connection_id, record.nango_integration)


def fresh_credentials(svc: AppServices, record: Connection) -> NangoConnection:
    """The connection with a valid access token (Nango refreshes expired ones), e.g. Slack's bot
    token for deploys. The refresh token is never requested."""
    if record.method != "nango":
        raise ConnectionError_(f"{record.connector} isn't connected through Nango")
    try:
        return _nango(svc).get_connection(record.nango_connection_id, record.nango_integration)
    except NangoError as exc:
        if exc.code == "invalid_credentials":
            # The provider refused the refresh (revoked, or Google's 7-day limit for "Testing" apps).
            found = svc.catalog.connectors.get(record.connector)
            name = found.name if found else record.connector
            raise ConnectionError_(
                f"Your {name} connection has expired. Reconnect it, then try again.", 409
            ) from None
        raise ConnectionError_(f"Couldn't read the {record.connector} connection: {exc}", 502) from None


class UserCredentials:
    """A user's secrets for deploy jobs (``adapters.base.SecretReader``); read on demand."""

    def __init__(self, svc: AppServices, user: User) -> None:
        self._svc = svc
        self._user = user

    def _record(self, connector_id: str) -> Connection:
        for record in self._user.connections:
            if record.connector == connector_id and record.status == "active":
                return record
        raise AdapterError(f"Connect {self._name(connector_id)} first")

    def _name(self, connector_id: str) -> str:
        found = self._svc.catalog.connectors.get(connector_id)
        return found.name if found else connector_id

    def oauth_tokens(self, connector: str) -> OAuthTokens:
        record = self._real(connector)
        try:
            conn = fresh_credentials(self._svc, record)
        except ConnectionError_ as exc:
            raise AdapterError(exc.message) from None
        if not conn.access_token:
            raise AdapterError(f"Your {self._name(connector)} connection has no access token; reconnect it")
        return OAuthTokens(access_token=conn.access_token, scope=conn.raw.get("scope"))

    def google_api(self, connector: str) -> GoogleApi:
        try:
            return google_api(self._svc, self._real(connector))
        except ConnectionError_ as exc:
            raise AdapterError(exc.message) from None

    def secret_value(self, connector: str) -> str:
        try:
            return read_secret(self._svc, self._user, self._real(connector))
        except ConnectionError_ as exc:
            raise AdapterError(exc.message) from None

    def _real(self, connector_id: str) -> Connection:
        record = self._record(connector_id)
        if record.method == "fake":
            raise AdapterError(
                f"{self._name(connector_id)} was connected with demo data; connect it for real"
            )
        return record


# ----------------------------------------------------------------------------- manual values


def save_manual(svc: AppServices, db: Session, user: User, connector_id: str, value: str) -> Connection:
    found = connector(svc, connector_id)
    if found.kind is not ConnectorKind.MANUAL:
        raise ConnectionError_("This connector is connected through a popup")
    value = value.strip()
    pattern, message = MANUAL_RULES.get(connector_id, (re.compile(r"^.{1,500}$"), "Enter a value"))
    if not pattern.match(value):
        raise ConnectionError_(message, 422)

    if found.secret:
        if svc.secret_box is None:
            raise ConnectionError_("Secret storage isn't configured on this server", 503)
        ciphertext = svc.secret_box.encrypt(value, _secret_context(user, connector_id))
        details = {"label": f"saved · ends with {value[-4:]}"}
    else:
        ciphertext = None
        details = {"label": value, "value": value}

    def update(record: Connection) -> None:
        record.method = "manual"
        record.nango_integration = record.nango_connection_id = None
        record.secret_ciphertext = ciphertext
        record.details = details

    return _store(svc, db, user, connector_id, update)


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


def save_fake(svc: AppServices, db: Session, user: User, connector_id: str) -> Connection:
    """Fake-platform mode: mark an account as connected with demo data."""
    connector(svc, connector_id)
    details: dict[str, Any] = {"label": f"{user.username} (demo data)", "value": "fake-value"}
    if connector_id == "slack":
        details |= {"slack_user_id": f"UFAKE{user.id:04d}", "team_name": "Demo workspace"}

    def update(record: Connection) -> None:
        record.method = "fake"
        record.nango_integration = record.nango_connection_id = None
        record.secret_ciphertext = None
        record.details = details

    return _store(svc, db, user, connector_id, update)


def delete(svc: AppServices, db: Session, user: User, connector_id: str) -> None:
    connector(svc, connector_id)
    record = get_connection(db, user, connector_id)
    if record is None:
        return
    removed = _nango_ref(record)
    db.delete(record)
    db.commit()
    if removed:
        _delete_in_nango(svc, *removed)


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
