"""Minimal n8n public API client (``/api/v1``, ``X-N8N-API-KEY``)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

# n8n unpublishes in the background; deleting right after answers 409 until it has finished.
DELETE_RETRY_WAITS = (0.5, 1, 2, 4, 8)


class N8nError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class N8nClient:
    def __init__(
        self, base_url: str, api_key: str, http: httpx.Client, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http
        self._sleep = sleep
        self._headers = {"X-N8N-API-KEY": api_key, "Accept": "application/json"}

    # ------------------------------------------------------------------ plumbing

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self._http.request(
                method, f"{self.base_url}/api/v1{path}", headers=self._headers, timeout=30, **kwargs
            )
        except httpx.HTTPError as exc:
            raise N8nError(f"n8n is unreachable: {exc.__class__.__name__}") from None
        if resp.status_code >= 400:
            raise N8nError(f"n8n error {resp.status_code}: {_message(resp)}", resp.status_code)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            raise N8nError("n8n returned a response that isn't JSON") from None

    @staticmethod
    def _id(data: Any, what: str) -> str:
        if isinstance(data, dict) and data.get("id") not in (None, ""):
            return str(data["id"])
        raise N8nError(f"n8n returned an unexpected {what}")

    def ping(self) -> None:
        """Any successful authenticated call (setup check)."""
        self._request("GET", "/workflows", params={"limit": 1})

    # ------------------------------------------------------------------ credentials

    def create_credential(self, name: str, credential_type: str, data: dict[str, Any]) -> str:
        created = self._request(
            "POST", "/credentials", json={"name": name, "type": credential_type, "data": data}
        )
        return self._id(created, "credential")

    def delete_credential(self, credential_id: str) -> None:
        self._delete(f"/credentials/{quote(credential_id, safe='')}")

    # ------------------------------------------------------------------ workflows

    def create_workflow(self, workflow: dict[str, Any]) -> str:
        return self._id(self._request("POST", "/workflows", json=workflow), "workflow")

    def publish_workflow(self, workflow_id: str) -> None:
        """Publish (activate). ``/publish`` is n8n 2.33+; older versions only have ``/activate``."""
        path = f"/workflows/{quote(workflow_id, safe='')}"
        try:
            self._request("POST", f"{path}/publish", json={})
        except N8nError as exc:
            if exc.status_code not in (404, 405):
                raise
            self._request("POST", f"{path}/activate", json={})

    def unpublish_workflow(self, workflow_id: str) -> None:
        """Unpublish (deactivate). ``/unpublish`` is n8n 2.33+; older versions only have ``/deactivate``."""
        path = f"/workflows/{quote(workflow_id, safe='')}"
        try:
            self._request("POST", f"{path}/unpublish", json={})
        except N8nError as exc:
            if exc.status_code not in (404, 405):
                raise
            self._request("POST", f"{path}/deactivate", json={})

    def delete_workflow(self, workflow_id: str) -> None:
        """Delete; n8n 2.x refuses (409) while the workflow is published, so unpublish and retry."""
        path = f"/workflows/{quote(workflow_id, safe='')}"
        try:
            self._delete(path)
            return
        except N8nError as exc:
            if exc.status_code != 409:
                raise
        self.unpublish_workflow(workflow_id)
        for wait in DELETE_RETRY_WAITS:
            try:
                self._delete(path)
                return
            except N8nError as exc:
                if exc.status_code != 409:
                    raise
            self._sleep(wait)
        self._delete(path)  # last try: its 409 is the error the caller reports

    def executions(self, workflow_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """The latest executions, without their (large) data."""
        data = self._request("GET", "/executions", params={"workflowId": workflow_id, "limit": limit})
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise N8nError("n8n returned an unexpected execution list")
        return [item for item in items if isinstance(item, dict)]

    def execution(self, execution_id: str) -> dict[str, Any]:
        """One execution with its data (node outputs), for the result summary."""
        data = self._request(
            "GET", f"/executions/{quote(execution_id, safe='')}", params={"includeData": "true"}
        )
        if not isinstance(data, dict):
            raise N8nError("n8n returned an unexpected execution")
        return data

    # ------------------------------------------------------------------ listing (orphan sweep)

    def list_all(self, kind: str, *, max_pages: int = 20) -> list[dict[str, Any]]:
        """Every workflow or credential (``kind`` = "workflows" / "credentials"), following cursors."""
        items: list[dict[str, Any]] = []
        cursor = None
        for _ in range(max_pages):
            params: dict[str, Any] = {"limit": 250}
            if cursor:
                params["cursor"] = cursor
            data = self._request("GET", f"/{kind}", params=params)
            page = data.get("data") if isinstance(data, dict) else None
            if not isinstance(page, list):
                raise N8nError(f"n8n returned an unexpected {kind} list")
            items += [item for item in page if isinstance(item, dict)]
            cursor = data.get("nextCursor")
            if not cursor:
                break
        return items

    # ------------------------------------------------------------------ webhooks

    def call_webhook(self, path: str, header: tuple[str, str], body: dict[str, Any]) -> None:
        """POST to a published workflow's production webhook (``/webhook/<path>``)."""
        url = f"{self.base_url}/webhook/{quote(path, safe='')}"
        try:
            resp = self._http.post(url, json=body, headers={header[0]: header[1]}, timeout=30)
        except httpx.HTTPError as exc:
            raise N8nError(f"n8n is unreachable: {exc.__class__.__name__}") from None
        if resp.status_code >= 400:
            raise N8nError(f"n8n webhook error {resp.status_code}: {_message(resp)}", resp.status_code)

    def _delete(self, path: str) -> None:
        try:
            self._request("DELETE", path)
        except N8nError as exc:
            if exc.status_code != 404:
                raise


def _message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:200] or "request failed"
    if isinstance(data, dict) and data.get("message"):
        return str(data["message"])[:300]
    return "request failed"
