"""Minimal n8n public API client (``/api/v1``, ``X-N8N-API-KEY``)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class N8nError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class N8nClient:
    def __init__(self, base_url: str, api_key: str, http: httpx.Client) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http
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

    # ------------------------------------------------------------------ credentials

    def create_credential(self, name: str, credential_type: str, data: dict[str, Any]) -> str:
        created = self._request(
            "POST", "/credentials", json={"name": name, "type": credential_type, "data": data}
        )
        return self._id(created, "credential")

    def delete_credential(self, credential_id: str) -> None:
        self._delete(f"/credentials/{quote(credential_id, safe='')}")

    def credential_schema(self, credential_type: str) -> dict[str, Any]:
        return self._request("GET", f"/credentials/schema/{quote(credential_type, safe='')}")

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

    def delete_workflow(self, workflow_id: str) -> None:
        self._delete(f"/workflows/{quote(workflow_id, safe='')}")

    def executions(self, workflow_id: str, limit: int = 10) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            "/executions",
            params={"workflowId": workflow_id, "includeData": "true", "limit": limit},
        )
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise N8nError("n8n returned an unexpected execution list")
        return [item for item in items if isinstance(item, dict)]

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
