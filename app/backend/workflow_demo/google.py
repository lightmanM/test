"""Google calls for a user's Google connection, made through Nango's proxy.

Nango holds the user's tokens and adds them to each call, so neither the demo nor n8n ever sees a
Google token. That also works when the Nango integration uses an OAuth app whose tokens can't be
exported (e.g. Nango's own developer app).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from workflow_demo.nango import NangoClient, NangoError

# Every call names its Google host, so it doesn't depend on which Nango Google provider is used.
GOOGLEAPIS = "https://www.googleapis.com"  # Drive, OAuth2 userinfo
SHEETS = "https://sheets.googleapis.com"
GMAIL = "https://gmail.googleapis.com"

UPTIME_SITES_HEADER = ("Property", "Status")
UPTIME_LOG_HEADER = ("date", "Property", "UP_FROM_UP", "DOWN_FROM_DOWN", "UP_FROM_DOWN", "DOWN_FROM_UP")


class GoogleError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class GoogleConnectionExpired(GoogleError):
    """Nango couldn't use the connection (revoked, expired, deleted): the user has to reconnect."""

    def __init__(self) -> None:
        super().__init__(
            "Your Google connection has expired or was revoked. Reconnect it, then try again.", 409
        )


@dataclass(frozen=True)
class Spreadsheet:
    id: str
    url: str


@dataclass(frozen=True)
class GoogleApi:
    """One user's Google connection in Nango."""

    nango: NangoClient
    connection_id: str
    integration: str

    def call(
        self,
        method: str,
        endpoint: str,
        *,
        base_url: str | None = None,
        params: Any = None,
        json: Any = None,
    ) -> httpx.Response:
        """The provider's response as is (any status); Nango's own failures raise."""
        try:
            resp = self.nango.proxy(
                method,
                endpoint,
                connection_id=self.connection_id,
                integration=self.integration,
                base_url=base_url,
                params=params,
                json=json,
            )
        except NangoError as exc:
            raise GoogleError(str(exc)) from None
        nango_error = nango_error_code(resp)
        if nango_error is not None:
            if nango_error in ("server_error", "connection_refresh_backoff"):
                # How Nango's proxy reports a missing connection or a refused token refresh.
                raise GoogleConnectionExpired()
            raise GoogleError(f"Nango error {resp.status_code}: {_message(resp)}")
        return resp

    def request_json(self, method: str, endpoint: str, *, what: str, **kwargs: Any) -> dict[str, Any]:
        """The JSON object of a successful response; any error raises."""
        resp = self.call(method, endpoint, **kwargs)
        if resp.status_code >= 400:
            raise GoogleError(f"{what} error {resp.status_code}: {_message(resp)}")
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            raise GoogleError(f"{what} returned an unexpected response") from None
        if not isinstance(data, dict):
            raise GoogleError(f"{what} returned an unexpected response")
        return data


def nango_error_code(resp: httpx.Response) -> str | None:
    """Nango's own errors carry a string ``error.code``; Google's carry a number."""
    if resp.status_code < 400:
        return None
    try:
        error = resp.json().get("error")
    except (ValueError, AttributeError):
        return None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


def _row(*values: str) -> dict[str, Any]:
    return {"values": [{"userEnteredValue": {"stringValue": v}} for v in values]}


def create_uptime_sheet(api: GoogleApi, title: str, sites: list[str]) -> Spreadsheet:
    """Create the spreadsheet the uptime template expects: ``Sites`` (seeded) and ``Log`` tabs."""
    body = {
        "properties": {"title": title},
        "sheets": [
            {
                "properties": {"title": "Sites"},
                "data": [{"rowData": [_row(*UPTIME_SITES_HEADER), *[_row(site) for site in sites]]}],
            },
            {"properties": {"title": "Log"}, "data": [{"rowData": [_row(*UPTIME_LOG_HEADER)]}]},
        ],
    }
    data = api.request_json("POST", "v4/spreadsheets", base_url=SHEETS, json=body, what="Google Sheets")
    try:
        return Spreadsheet(id=str(data["spreadsheetId"]), url=str(data["spreadsheetUrl"]))
    except KeyError:
        raise GoogleError("Google Sheets returned an unexpected response") from None


def spreadsheet_url(api: GoogleApi, spreadsheet_id: str) -> str | None:
    """The spreadsheet's URL if the user can still open it (not deleted), else None."""
    resp = api.call(
        "GET",
        f"v4/spreadsheets/{quote(spreadsheet_id, safe='')}",
        base_url=SHEETS,
        params={"fields": "spreadsheetId,spreadsheetUrl"},
    )
    if resp.status_code in (403, 404):
        return None
    if resp.status_code >= 400:
        raise GoogleError(f"Google Sheets error {resp.status_code}: {_message(resp)}")
    try:
        return str(resp.json()["spreadsheetUrl"])
    except (ValueError, KeyError, TypeError):
        raise GoogleError("Google Sheets returned an unexpected response") from None


def replace_uptime_sites(api: GoogleApi, spreadsheet_id: str, sites: list[str]) -> None:
    """Replace the ``Sites`` rows below the header with ``sites`` (Status starts blank, i.e. UP)."""
    values = f"v4/spreadsheets/{quote(spreadsheet_id, safe='')}/values"
    api.request_json(
        "POST",
        f"{values}/{quote('Sites!A2:B', safe='')}:clear",
        base_url=SHEETS,
        json={},
        what="Google Sheets",
    )
    if sites:
        api.request_json(
            "PUT",
            f"{values}/{quote('Sites!A2', safe='')}",
            base_url=SHEETS,
            params={"valueInputOption": "RAW"},
            json={"values": [[site] for site in sites]},
            what="Google Sheets",
        )


def delete_file(api: GoogleApi, file_id: str) -> None:
    """Best effort: remove a file the demo created (drive.file scope covers it)."""
    with contextlib.suppress(GoogleError):
        api.call("DELETE", f"drive/v3/files/{quote(file_id, safe='')}", base_url=GOOGLEAPIS)


def check_connection(api: GoogleApi) -> None:
    """Raise ``GoogleConnectionExpired`` if Nango can no longer use the connection (one cheap call)."""
    api.call("GET", "oauth2/v3/userinfo", base_url=GOOGLEAPIS)


def user_email(api: GoogleApi) -> str | None:
    """The account's email address (OpenID userinfo), shown next to the connection."""
    try:
        resp = api.call("GET", "oauth2/v3/userinfo", base_url=GOOGLEAPIS)
        email = resp.json().get("email") if resp.status_code == 200 else None
    except (GoogleError, ValueError, AttributeError):
        return None
    return email if isinstance(email, str) else None


def _message(resp: httpx.Response) -> str:
    try:
        error = resp.json().get("error") or {}
        return str(error.get("message") or "request failed")[:300]
    except (ValueError, AttributeError):
        return resp.text[:200] or "request failed"
