"""The Google relay: deployed n8n workflows call Google through the demo, which forwards each call
to Nango's proxy as the deployment owner's Google connection.

n8n never holds a Google token or the Nango secret key. It holds one key per deployment (an n8n
Header Auth credential, ``Authorization: Bearer <deployment id>.<random>``, see ``relay_keys``).
A key works while its deployment is active and only for the calls its workflow needs
(``google_apis`` in catalog.yaml): cells of the deployment's own spreadsheet, or reading Gmail
messages. Everything else is refused before it reaches Nango.
"""

from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC
from typing import Any
from urllib.parse import quote

from sqlalchemy.orm import Session

from workflow_demo import google
from workflow_demo.catalog.models import CredentialSource, GoogleAccess, WorkflowEntry
from workflow_demo.db import Deployment, utcnow
from workflow_demo.relay_keys import KEY_REF, digest
from workflow_demo.services import connections
from workflow_demo.services.container import AppServices
from workflow_demo.services.states import Status

MAX_BODY = 64 * 1024
INVALID_KEY = "Invalid Google relay key"

_TOKEN = re.compile(r"^(\d{1,12})\.([A-Za-z0-9_-]{32,128})$")
_SHEET = r"(?P<sheet>[A-Za-z0-9_-]{10,100})"
_RANGE = r"(?P<range>[A-Za-z0-9]{1,40}![A-Z]{1,3}[0-9]{0,7}(?::[A-Z]{1,3}[0-9]{0,7})?)"
_MESSAGE = r"(?P<message>[A-Za-z0-9]{1,64})"


class RelayError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class RelayRoute:
    access: GoogleAccess
    method: str
    pattern: re.Pattern[str]
    base_url: str
    params: frozenset[str]  # query parameters passed on; others are dropped


def _route(access: GoogleAccess, method: str, pattern: str, base_url: str, *params: str) -> RelayRoute:
    return RelayRoute(access, method, re.compile(pattern), base_url, frozenset(params))


VALUE_READ = ("majorDimension", "valueRenderOption", "dateTimeRenderOption")
VALUE_WRITE = ("valueInputOption", "includeValuesInResponse", "responseValueRenderOption")
ROUTES = (
    _route(
        GoogleAccess.SHEETS, "GET", rf"v4/spreadsheets/{_SHEET}/values/{_RANGE}", google.SHEETS, *VALUE_READ
    ),
    _route(
        GoogleAccess.SHEETS, "PUT", rf"v4/spreadsheets/{_SHEET}/values/{_RANGE}", google.SHEETS, *VALUE_WRITE
    ),
    _route(
        GoogleAccess.SHEETS,
        "POST",
        rf"v4/spreadsheets/{_SHEET}/values/{_RANGE}:append",
        google.SHEETS,
        *VALUE_WRITE,
        "insertDataOption",
    ),
    _route(
        GoogleAccess.GMAIL_READ,
        "GET",
        r"gmail/v1/users/me/messages",
        google.GMAIL,
        "q",
        "maxResults",
        "pageToken",
        "labelIds",
        "includeSpamTrash",
    ),
    _route(
        GoogleAccess.GMAIL_READ,
        "GET",
        rf"gmail/v1/users/me/messages/{_MESSAGE}",
        google.GMAIL,
        "format",
        "metadataHeaders",
    ),
)
# The relay's path prefix per Google API ({relay}/sheets/v4/... and {relay}/gmail/v1/...).
PREFIXES = {GoogleAccess.SHEETS: "sheets/", GoogleAccess.GMAIL_READ: ""}


@dataclass(frozen=True)
class RelayResponse:
    status_code: int
    content: bytes
    media_type: str


def relay_slot(entry: WorkflowEntry) -> tuple[str, str] | None:
    """(slot name, connector) of the workflow's Google relay credential, if it has one."""
    for name, slot in (entry.n8n.credentials if entry.n8n else {}).items():
        if slot.source is CredentialSource.GOOGLE_RELAY:
            return name, slot.ref
    return None


# ----------------------------------------------------------------------------- relay


def relay(
    svc: AppServices,
    db: Session,
    *,
    authorization: str | None,
    method: str,
    path: str,
    query: list[tuple[str, str]],
    body: bytes,
) -> RelayResponse:
    dep = _authenticate(db, authorization)
    entry = _workflow(svc, dep)
    route, match = _match(method, path)
    if route.access not in entry.n8n.google_apis:
        raise RelayError(403, f"{entry.name} isn't allowed to make this Google call")
    groups = match.groupdict()
    if "sheet" in groups and groups["sheet"] != (dep.platform_refs or {}).get("spreadsheet_id"):
        raise RelayError(403, "Only the spreadsheet created for this deployment can be used")
    api = _google_api(svc, dep, entry)
    params = [(k, v) for k, v in query if k in route.params]
    payload: Any = None
    if method in ("POST", "PUT"):
        payload = _json_body(body)
    try:
        resp = api.call(
            method, _endpoint(route, groups), base_url=route.base_url, params=params, json=payload
        )
    except google.GoogleConnectionExpired as exc:
        raise RelayError(409, str(exc)) from None
    except google.GoogleError as exc:
        raise RelayError(502, str(exc)) from None
    media_type = resp.headers.get("content-type", "application/json").split(";")[0].strip()
    return RelayResponse(resp.status_code, resp.content, media_type or "application/json")


def _authenticate(db: Session, authorization: str | None) -> Deployment:
    scheme, _, key = (authorization or "").partition(" ")
    match = _TOKEN.match(key.strip()) if scheme.lower() == "bearer" else None
    dep = db.get(Deployment, int(match.group(1))) if match else None
    stored = (dep.platform_refs or {}).get(KEY_REF) if dep is not None else None
    if not isinstance(stored, str) or not hmac.compare_digest(stored, digest(key.strip())):
        raise RelayError(401, INVALID_KEY)
    expires_at = dep.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if dep.status != Status.ACTIVE or (expires_at is not None and expires_at <= utcnow()):
        raise RelayError(403, "This deployment isn't active")
    return dep


def _workflow(svc: AppServices, dep: Deployment) -> WorkflowEntry:
    try:
        entry = svc.catalog.workflow(dep.workflow_id)
    except KeyError:
        raise RelayError(403, "This workflow is no longer in the catalog") from None
    if entry.n8n is None or relay_slot(entry) is None:
        raise RelayError(403, "This workflow doesn't use the Google relay")
    return entry


def _match(method: str, path: str) -> tuple[RelayRoute, re.Match[str]]:
    for route in ROUTES:
        prefix = PREFIXES[route.access]
        if route.method == method and path.startswith(prefix):
            match = route.pattern.fullmatch(path[len(prefix) :])
            if match:
                return route, match
    raise RelayError(404, "This Google call isn't available through the demo")


def _endpoint(route: RelayRoute, groups: dict[str, str]) -> str:
    """The upstream path, rebuilt from the checked parts (each one URL-escaped)."""
    escaped = {k: quote(v, safe="") for k, v in groups.items()}
    if route.access is GoogleAccess.GMAIL_READ:
        return "gmail/v1/users/me/messages" + (f"/{escaped['message']}" if "message" in escaped else "")
    endpoint = f"v4/spreadsheets/{escaped['sheet']}/values/{escaped['range']}"
    return endpoint + (":append" if route.method == "POST" else "")


def _google_api(svc: AppServices, dep: Deployment, entry: WorkflowEntry) -> google.GoogleApi:
    _, connector = relay_slot(entry)  # type: ignore[misc]  # checked in _workflow
    for record in dep.user.connections:
        if record.connector == connector and record.status == "active" and record.method == "nango":
            try:
                return connections.google_api(svc, record)
            except connections.ConnectionError_ as exc:
                raise RelayError(exc.status_code if exc.status_code >= 500 else 409, exc.message) from None
    raise RelayError(409, "Google isn't connected for this deployment any more; reconnect it in the demo")


def _json_body(body: bytes) -> Any:
    if len(body) > MAX_BODY:
        raise RelayError(413, "Request body too large")
    try:
        return json.loads(body or b"{}")
    except ValueError:
        raise RelayError(400, "The request body must be JSON") from None
