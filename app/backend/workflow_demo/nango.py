"""Minimal Nango Cloud client (REST; Nango has no official Python SDK)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class NangoError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ConnectSession:
    token: str
    expires_at: str
    connect_link: str | None


@dataclass(frozen=True)
class NangoConnection:
    connection_id: str
    provider_config_key: str
    provider: str | None
    tags: dict[str, str]
    credentials: dict[str, Any]  # access_token, refresh_token?, expires_at?, raw

    @property
    def access_token(self) -> str | None:
        return self.credentials.get("access_token")

    @property
    def raw(self) -> dict[str, Any]:
        return self.credentials.get("raw") or {}


class NangoClient:
    def __init__(
        self, secret_key: str, host: str = "https://api.nango.dev", http: httpx.Client | None = None
    ) -> None:
        self._host = host.rstrip("/")
        self._http = http or httpx.Client(timeout=20)
        self._headers = {"Authorization": f"Bearer {secret_key}"}

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resp = self._http.request(method, f"{self._host}{path}", headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            raise NangoError(f"Nango is unreachable: {exc.__class__.__name__}") from None
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("error", {})
                message = detail.get("message") if isinstance(detail, dict) else str(detail)
            except ValueError:
                message = resp.text[:200]
            raise NangoError(
                f"Nango error {resp.status_code}: {message or 'request failed'}", resp.status_code
            )
        return resp.json() if resp.content else {}

    def create_connect_session(self, integration: str, tags: dict[str, str]) -> ConnectSession:
        data = self._request(
            "POST", "/connect/sessions", json={"tags": tags, "allowed_integrations": [integration]}
        )["data"]
        return ConnectSession(
            token=data["token"], expires_at=data["expires_at"], connect_link=data.get("connect_link")
        )

    def get_connection(
        self,
        connection_id: str,
        integration: str,
        *,
        force_refresh: bool = False,
        refresh_token: bool = False,
    ) -> NangoConnection:
        params = {"provider_config_key": integration}
        if force_refresh:
            params["force_refresh"] = "true"
        if refresh_token:
            params["refresh_token"] = "true"
        data = self._request("GET", f"/connections/{connection_id}", params=params)
        return NangoConnection(
            connection_id=data["connection_id"],
            provider_config_key=data["provider_config_key"],
            provider=data.get("provider"),
            tags=data.get("tags") or {},
            credentials=data.get("credentials") or {},
        )

    def delete_connection(self, connection_id: str, integration: str) -> None:
        try:
            self._request(
                "DELETE", f"/connections/{connection_id}", params={"provider_config_key": integration}
            )
        except NangoError as exc:
            if exc.status_code != 404:
                raise
