"""Minimal Nango Cloud client (REST; Nango has no official Python SDK)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx


class NangoError(Exception):
    def __init__(self, message: str, status_code: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code  # Nango's `error.code`, e.g. `invalid_credentials` when a refresh was refused


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
    def refresh_token(self) -> str | None:
        return self.credentials.get("refresh_token")

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
            code = None
            try:
                detail = resp.json().get("error", {})
                message = detail.get("message") if isinstance(detail, dict) else str(detail)
                code = detail.get("code") if isinstance(detail, dict) else None
            except ValueError:
                message = resp.text[:200]
            raise NangoError(
                f"Nango error {resp.status_code}: {message or 'request failed'}", resp.status_code, code
            )
        try:
            return resp.json() if resp.content else {}
        except ValueError:
            raise NangoError("Nango returned a response that isn't JSON") from None

    def integration_keys(self) -> set[str]:
        """Keys of the integrations configured in Nango (setup check)."""
        data = self._request("GET", "/integrations")
        items = data.get("data", data.get("configs")) if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise NangoError("Nango returned an unexpected integration list")
        return {str(i.get("unique_key") or i.get("id")) for i in items if isinstance(i, dict)}

    def create_connect_session(self, integration: str, tags: dict[str, str]) -> ConnectSession:
        data = self._request(
            "POST", "/connect/sessions", json={"tags": tags, "allowed_integrations": [integration]}
        )
        try:
            data = data["data"]
            return ConnectSession(
                token=data["token"], expires_at=data["expires_at"], connect_link=data.get("connect_link")
            )
        except (KeyError, TypeError):
            raise NangoError("Nango returned an unexpected connect session") from None

    def get_connection(
        self,
        connection_id: str,
        integration: str,
        *,
        force_refresh: bool = False,
        include_refresh_token: bool = False,
    ) -> NangoConnection:
        """Read a connection. Nango refreshes an expired access token itself; ``force_refresh``
        refreshes regardless. The refresh token is returned only with ``include_refresh_token``
        (needed when another platform must refresh the token itself, e.g. n8n)."""
        params = {"provider_config_key": integration}
        if force_refresh:
            params["force_refresh"] = "true"
        if include_refresh_token:
            params["refresh_token"] = "true"
        data = self._request("GET", _connection_path(connection_id), params=params)
        try:
            return NangoConnection(
                connection_id=data["connection_id"],
                provider_config_key=data["provider_config_key"],
                provider=data.get("provider"),
                tags=data.get("tags") or {},
                credentials=data.get("credentials") or {},
            )
        except (KeyError, TypeError):
            raise NangoError("Nango returned an unexpected connection") from None

    def delete_connection(self, connection_id: str, integration: str) -> None:
        try:
            self._request(
                "DELETE", _connection_path(connection_id), params={"provider_config_key": integration}
            )
        except NangoError as exc:
            if exc.status_code != 404:
                raise


def _connection_path(connection_id: str) -> str:
    return f"/connections/{quote(connection_id, safe='')}"
