"""Google calls made with the user's own token (Nango): the uptime monitor's spreadsheet."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE_FILES_API = "https://www.googleapis.com/drive/v3/files"

UPTIME_SITES_HEADER = ("Property", "Status")
UPTIME_LOG_HEADER = ("date", "Property", "UP_FROM_UP", "DOWN_FROM_DOWN", "UP_FROM_DOWN", "DOWN_FROM_UP")


class GoogleError(Exception):
    pass


@dataclass(frozen=True)
class Spreadsheet:
    id: str
    url: str


def _row(*values: str) -> dict[str, Any]:
    return {"values": [{"userEnteredValue": {"stringValue": v}} for v in values]}


def create_uptime_sheet(http: httpx.Client, access_token: str, title: str, sites: list[str]) -> Spreadsheet:
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
    try:
        resp = http.post(
            SHEETS_API, json=body, headers={"Authorization": f"Bearer {access_token}"}, timeout=30
        )
    except httpx.HTTPError as exc:
        raise GoogleError(f"Google Sheets is unreachable: {exc.__class__.__name__}") from None
    if resp.status_code >= 400:
        raise GoogleError(f"Google Sheets error {resp.status_code}: {_message(resp)}")
    try:
        data = resp.json()
        return Spreadsheet(id=data["spreadsheetId"], url=data["spreadsheetUrl"])
    except (ValueError, KeyError, TypeError):
        raise GoogleError("Google Sheets returned an unexpected response") from None


def spreadsheet_url(http: httpx.Client, access_token: str, spreadsheet_id: str) -> str | None:
    """The spreadsheet's URL if the user can still open it (not deleted), else None."""
    try:
        resp = http.get(
            f"{SHEETS_API}/{quote(spreadsheet_id, safe='')}",
            params={"fields": "spreadsheetId,spreadsheetUrl"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise GoogleError(f"Google Sheets is unreachable: {exc.__class__.__name__}") from None
    if resp.status_code in (403, 404):
        return None
    if resp.status_code >= 400:
        raise GoogleError(f"Google Sheets error {resp.status_code}: {_message(resp)}")
    try:
        return str(resp.json()["spreadsheetUrl"])
    except (ValueError, KeyError, TypeError):
        raise GoogleError("Google Sheets returned an unexpected response") from None


def delete_file(http: httpx.Client, access_token: str, file_id: str) -> None:
    """Best effort: remove a file the demo created (drive.file scope covers it)."""
    with contextlib.suppress(httpx.HTTPError):
        http.delete(
            f"{DRIVE_FILES_API}/{quote(file_id, safe='')}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )


def _message(resp: httpx.Response) -> str:
    try:
        error = resp.json().get("error") or {}
        return str(error.get("message") or "request failed")[:300]
    except (ValueError, AttributeError):
        return resp.text[:200] or "request failed"
