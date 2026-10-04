"""Make Bridge portal API client (``https://<zone>/portal/api/bridge``).

Every request carries a short-lived JWT signed with the Bridge secret (HS256, ``kid`` = key ID)
whose ``sub`` is the end user: Make keeps each user's scenarios and connections in their own
sandbox under the owner's account.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any
from urllib.parse import quote

import httpx

TOKEN_SECONDS = 120


class BridgeError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_jwt(subject: str, key_id: str, secret: str, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": key_id}
    claims = {"sub": subject, "jti": str(uuid.uuid4()), "iat": issued, "exp": issued + TOKEN_SECONDS}
    signing_input = f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(claims).encode())}"
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


class BridgeClient:
    def __init__(
        self, zone: str, key_id: str, secret: str, http: httpx.Client, team_id: int | None = None
    ) -> None:
        self.base_url = f"https://{zone.removeprefix('https://').rstrip('/')}/portal/api/bridge"
        self._key_id = key_id
        self._secret = secret
        self._http = http
        self._team_id = team_id

    def _request(self, method: str, path: str, subject: str, *, timeout: float = 30, **kwargs: Any) -> Any:
        token = sign_jwt(subject, self._key_id, self._secret)
        params = {"teamId": self._team_id} if self._team_id else None
        try:
            resp = self._http.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise BridgeError(f"Make is unreachable: {exc.__class__.__name__}") from None
        if resp.status_code >= 400:
            raise BridgeError(f"Make error {resp.status_code}: {_message(resp)}", resp.status_code)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            raise BridgeError("Make returned a response that isn't JSON") from None

    def ping(self, subject: str, *, timeout: float = 30) -> None:
        """Any successful answer from the Bridge API (used as the availability check)."""
        self._request("GET", "/integrations/", subject, timeout=timeout)

    def integrations(self, subject: str) -> list[dict[str, Any]]:
        """The end user's integrations (``{"integrations": [{"scenario": {...}}, ...]}``)."""
        data = self._request("GET", "/integrations/", subject)
        items = data.get("integrations") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise BridgeError("Make returned an unexpected integration list")
        return [item for item in items if isinstance(item, dict)]

    def init(self, subject: str, template_id: int, redirect_uri: str, scenario_name: str) -> tuple[str, str]:
        """Start an integration; returns ``(public_url, flow_id)``. The user finishes it in Make's popup."""
        body = {
            "redirectUri": redirect_uri,
            "allowReusingComponents": True,  # offer connections the user made before
            "allowCreatingComponents": True,
            "autoActivate": False,  # the demo activates after checking the result
            "autoFinalize": True,
            "scenario": {"name": scenario_name, "enable": False},
        }
        data = self._request("POST", f"/integrations/init/{int(template_id)}", subject, json=body)
        try:
            return str(data["publicUrl"]), str(data["flow"]["id"])
        except (KeyError, TypeError):
            raise BridgeError("Make returned an unexpected init response") from None

    def check_init(self, subject: str, flow_id: str) -> dict[str, Any]:
        data = self._request("GET", f"/integrations/check-init/{quote(flow_id, safe='')}", subject)
        flow = data.get("flow") if isinstance(data, dict) else None
        if not isinstance(flow, dict):
            raise BridgeError("Make returned an unexpected status")
        return flow

    def activate(self, subject: str, scenario_id: int) -> None:
        self._request("POST", f"/integrations/{int(scenario_id)}/activate", subject)

    def deactivate(self, subject: str, scenario_id: int) -> None:
        self._request("POST", f"/integrations/{int(scenario_id)}/deactivate", subject)

    def delete(self, subject: str, scenario_id: int) -> None:
        try:
            self._request("DELETE", f"/integrations/{int(scenario_id)}", subject)
        except BridgeError as exc:
            if exc.status_code != 404:
                raise

    def run(self, subject: str, scenario_id: int) -> str | None:
        data = self._request("POST", f"/integrations/{int(scenario_id)}/run", subject)
        return str(data["executionId"]) if isinstance(data, dict) and data.get("executionId") else None

    def logs(self, subject: str, scenario_id: int) -> list[dict[str, Any]]:
        data = self._request("GET", f"/scenarios/{int(scenario_id)}/logs", subject)
        if isinstance(data, dict):  # tolerate a wrapped list
            data = data.get("scenarioLogs", data.get("logs", data.get("data")))
        if not isinstance(data, list):
            raise BridgeError("Make returned unexpected logs")
        return [item for item in data if isinstance(item, dict)]


def _message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:200] or "request failed"
    if isinstance(data, dict):
        for key in ("message", "detail", "error"):
            if isinstance(data.get(key), str):
                return data[key][:300]
    return "request failed"
