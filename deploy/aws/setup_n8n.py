#!/usr/bin/env python3
"""One-time n8n setup on the AWS server: the owner account and an API key for the demo.

    N8N_OWNER_EMAIL=you@example.com python3 deploy/aws/setup_n8n.py
    deploy/aws/deploy.sh          # so the demo picks up the key

Reads N8N_HOST from deploy/aws/.env. Saves the owner login to deploy/aws/n8n-owner.env (stays on
this machine; deploy.sh doesn't copy it) and the key as N8N_API_KEY in deploy/production.env.
Re-running logs in with the saved owner and adds a new key. Uses n8n's internal REST API
(/rest/owner/setup, /rest/login, /rest/api-keys), checked against n8n 2.41.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "deploy/aws/.env"
OWNER = ROOT / "deploy/aws/n8n-owner.env"
PRODUCTION = ROOT / "deploy/production.env"
KEY_LABEL = "workflow-demo"


def read_env(path: Path) -> dict[str, str]:
    return dict(re.findall(r"^([A-Z0-9_]+)=(.*)$", path.read_text(), re.MULTILINE)) if path.exists() else {}


def write_value(path: Path, key: str, value: str) -> None:
    text = path.read_text() if path.exists() else ""
    text, found = re.subn(rf"^{key}=.*$", f"{key}={value}", text, flags=re.MULTILINE)
    if not found:
        text = f"{text.rstrip()}\n{key}={value}\n".lstrip()
    path.write_text(text)
    path.chmod(0o600)


class N8n:
    def __init__(self, host: str) -> None:
        self._base = f"https://{host}/rest"
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def call(self, method: str, path: str, body: object = None) -> object:
        request = urllib.request.Request(
            self._base + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "browser-id": "workflow-demo-setup"},
        )
        try:
            with self._opener.open(request, timeout=30) as resp:
                return json.loads(resp.read() or b"{}").get("data")
        except urllib.error.HTTPError as exc:
            raise N8nError(exc.code, exc.read()[:300].decode(errors="replace")) from None


class N8nError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"n8n answered {status}: {detail}")
        self.status = status


def sign_in(n8n: N8n, owner: dict[str, str]) -> None:
    """Create the owner on a fresh instance; otherwise log in as the saved owner."""
    email, password = owner["N8N_OWNER_EMAIL"], owner["N8N_OWNER_PASSWORD"]
    try:
        n8n.call(
            "POST",
            "/owner/setup",
            {"email": email, "firstName": "Demo", "lastName": "Owner", "password": password},
        )
        print(f"Created the n8n owner {email}")
    except N8nError as exc:
        if exc.status != 400:  # 400: the instance already has an owner
            raise
        n8n.call("POST", "/login", {"emailOrLdapLoginId": email, "password": password})
        print(f"Logged in as the existing owner {email}")


def main() -> None:
    host = read_env(INFRA).get("N8N_HOST") or sys.exit("Set N8N_HOST in deploy/aws/.env")
    owner = read_env(OWNER)
    if not owner:
        email = os.environ.get("N8N_OWNER_EMAIL") or sys.exit("Set N8N_OWNER_EMAIL for the first run")
        # Saved before the owner is created, so a failed run never loses the password.
        owner = {"N8N_OWNER_EMAIL": email, "N8N_OWNER_PASSWORD": secrets.token_urlsafe(24) + "A1"}
        for key, value in owner.items():
            write_value(OWNER, key, value)
    n8n = N8n(host)
    sign_in(n8n, owner)
    scopes = n8n.call("GET", "/api-keys/scopes")
    created = n8n.call("POST", "/api-keys", {"label": KEY_LABEL, "scopes": scopes, "expiresAt": None})
    write_value(PRODUCTION, "N8N_API_KEY", created["rawApiKey"])
    print(
        f"Created API key '{KEY_LABEL}' ({len(scopes)} scopes)"
        f" → N8N_API_KEY in {PRODUCTION.relative_to(ROOT)}"
    )
    print(f"Owner login for https://{host}: {OWNER.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except (N8nError, urllib.error.URLError) as exc:
        sys.exit(f"n8n setup failed: {exc}")
