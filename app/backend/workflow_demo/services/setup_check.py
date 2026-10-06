"""Admin setup check: is each piece of owner configuration present and working?

Each check is ``ok`` (configured and answering), ``missing`` (not configured: the features that
need it show as "not set up"), ``error`` (configured but failing) or ``info``. Live calls are short
and read-only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal

import httpx
from sqlalchemy import text

from workflow_demo.adapters.base import AdapterError
from workflow_demo.catalog.models import ConnectorKind, Platform
from workflow_demo.n8n.client import N8nClient, N8nError
from workflow_demo.nango import NangoError
from workflow_demo.relay_keys import RELAY_PATH
from workflow_demo.services import deployments as svc_deployments
from workflow_demo.services.container import AppServices
from workflow_demo.services.google_relay import INVALID_KEY

State = Literal["ok", "missing", "error", "info"]
TIMEOUT = 5


@dataclass(frozen=True)
class Check:
    name: str
    state: State
    detail: str


def _probe(name: str, call: Callable[[], str]) -> Check:
    try:
        return Check(name, "ok", call())
    except Exception as exc:  # noqa: BLE001 - every failure is reported, never raised
        return Check(name, "error", str(exc)[:300] or exc.__class__.__name__)


def _get(svc: AppServices, url: str, **kwargs: Any) -> httpx.Response:
    resp = svc.http.get(url, timeout=TIMEOUT, **kwargs)
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} from {url.split('?')[0]}")
    return resp


def run_checks(svc: AppServices) -> dict[str, Any]:
    s = svc.settings
    checks: list[Check] = []

    def database() -> str:
        with svc.db.session() as db:
            db.execute(text("select 1"))
        return "reachable"

    checks.append(_probe("Database", database))
    if s.fake_platforms:
        checks.append(Check("Mode", "info", "Fake platforms: deploys are simulated (DEMO_FAKE_PLATFORMS=1)"))

    # Connections
    if svc.nango is None:
        checks.append(
            Check("Nango", "missing", "NANGO_SECRET_KEY not set: Slack and Google can't be connected")
        )
    else:
        wanted = {c.integration for c in svc.catalog.connectors.values() if c.kind is ConnectorKind.NANGO}

        def nango() -> str:
            try:
                keys = svc.nango.integration_keys()
            except NangoError as exc:
                raise RuntimeError(str(exc)) from None
            missing = sorted(wanted - keys)
            if missing:
                raise RuntimeError(f"integrations missing in Nango: {', '.join(missing)}")
            return f"integrations {', '.join(sorted(wanted))} configured"

        checks.append(_probe("Nango", nango))
    checks.append(
        Check("Encryption key", "ok", "set")
        if svc.secret_box is not None
        else Check(
            "Encryption key", "missing", "DATA_ENCRYPTION_KEY not set: the Meegle token can't be saved"
        )
    )

    # n8n and what its workflows use
    if s.n8n_base_url and s.n8n_api_key:
        client = N8nClient(s.n8n_base_url, s.n8n_api_key.get_secret_value(), svc.http)

        def n8n() -> str:
            try:
                client.ping()
            except N8nError as exc:
                raise RuntimeError(str(exc)) from None
            return f"API key accepted by {s.n8n_base_url}"

        checks.append(_probe("n8n", n8n))
        relay_url = (s.relay_base_url or "").rstrip("/")

        def relay() -> str:
            # n8n calls Google at this address (Nango's proxy behind it). Without a key the relay
            # answers 401 with its own error; anything else means the address is wrong or blocked.
            url = f"{relay_url}{RELAY_PATH}/check"
            resp = svc.http.get(url, timeout=TIMEOUT)
            try:
                message = resp.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = None
            if resp.status_code != 401 or message != INVALID_KEY:
                raise RuntimeError(
                    f"HTTP {resp.status_code} from {url}: not the demo's Google relay (RELAY_BASE_URL)"
                )
            return f"n8n calls Google through {relay_url}{RELAY_PATH} and Nango's proxy"

        checks.append(
            _probe("Google relay", relay)
            if relay_url
            else Check("Google relay", "missing", "RELAY_BASE_URL not set (uptime monitor, Medium digest)")
        )
    else:
        checks.append(Check("n8n", "missing", "N8N_BASE_URL / N8N_API_KEY not set"))
    if s.openai_api_key:

        def llm() -> str:
            key = s.openai_api_key.get_secret_value()
            _get(svc, f"{s.openai_base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"})
            return "key accepted"

        checks.append(_probe("LLM API", llm))
    else:
        checks.append(Check("LLM API", "missing", "OPENAI_API_KEY not set (Medium digest)"))
    if s.reader_base_url and s.reader_api_token:

        def reader() -> str:
            _get(svc, f"{s.reader_base_url.rstrip('/')}/healthz")
            return "healthy"

        checks.append(_probe("Medium reader", reader))
    else:
        checks.append(Check("Medium reader", "missing", "READER_BASE_URL / READER_API_TOKEN not set"))

    # Make and the shared bot report through their adapters.
    for platform, name in ((Platform.MAKE, "Make Bridge"), (Platform.MODAL, "Slack bot")):
        try:
            availability = svc.registry.get(platform).check_available()
        except AdapterError as exc:
            checks.append(Check(name, "missing", str(exc)))
            continue
        if availability.available:
            checks.append(Check(name, "ok", "available"))
        else:
            state: State = "missing" if "Not set up" in (availability.reason or "") else "error"
            checks.append(Check(name, state, availability.reason or "unavailable"))

    workflows = []
    for entry in svc.catalog.workflows:
        availability = svc_deployments.availability(svc, entry)
        workflows.append(
            {
                "id": entry.id,
                "name": entry.name,
                "platform": entry.platform.value,
                "available": availability.available,
                "reason": availability.reason,
            }
        )
    return {"checks": [asdict(c) for c in checks], "workflows": workflows}
