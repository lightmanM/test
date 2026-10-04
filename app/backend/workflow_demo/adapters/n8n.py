"""Deploy the n8n workflows (uptime monitor, Meegle digest, Medium digest) under the owner's account.

Per deployment: the user's credentials are created in n8n (Google with our OAuth client so n8n can
refresh tokens itself; Slack bot token; Meegle MCP header; owner-provided OpenAI and reader keys),
the template is filled in and gets a header-authenticated "Run now" webhook, then the workflow is
created and published. Results come from the workflow's executions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from workflow_demo import google
from workflow_demo.adapters.base import (
    AdapterError,
    Availability,
    DeployContext,
    DeployResult,
    RunStarted,
    RunSummary,
)
from workflow_demo.catalog.loader import load_template
from workflow_demo.catalog.models import (
    CredentialSlot,
    CredentialSource,
    Platform,
    ValueSource,
    WorkflowEntry,
)
from workflow_demo.config import Settings
from workflow_demo.n8n.client import N8nClient, N8nError
from workflow_demo.n8n.transform import RUN_HEADER, CredentialRef, RunHook, TransformError, build_workflow

log = logging.getLogger(__name__)

GOOGLE_TYPES = {"googleSheetsOAuth2Api", "gmailOAuth2"}
# Header each manual secret is sent in (the template's HTTP nodes use an httpHeaderAuth slot).
SECRET_HEADERS = {"meegle_mcp_token": "X-Mcp-Token"}
STATUS = {
    "success": "success",
    "error": "error",
    "crashed": "error",
    "canceled": "error",
    "running": "running",
    "new": "running",
    "unknown": "running",
    "waiting": "waiting",
}
MAX_SUMMARY = 4000


@dataclass
class _Created:
    """What a deploy created so far, removed again if a later step fails."""

    credential_ids: list[str] = field(default_factory=list)
    workflow_id: str | None = None
    spreadsheet_id: str | None = None
    spreadsheet_url: str | None = None
    google_token: str | None = None


class N8nAdapter:
    platform = Platform.N8N

    def __init__(self, settings: Settings, client: N8nClient, http: httpx.Client) -> None:
        self._settings = settings
        self._client = client
        self._http = http
        self._run_key = hashlib.sha256(
            b"n8n-run:" + settings.session_secret.get_secret_value().encode()
        ).digest()

    # ------------------------------------------------------------------ availability

    def check_available(self, entry: WorkflowEntry | None = None) -> Availability:
        missing = self._missing_config(entry) if entry is not None else []
        if missing:
            return Availability(False, f"Not set up on this server yet (missing {', '.join(missing)})")
        return Availability(True)

    def _missing_config(self, entry: WorkflowEntry) -> list[str]:
        s = self._settings
        needs: list[str] = []
        spec = entry.n8n
        if spec is None:
            return ["n8n template"]
        for slot in spec.credentials.values():
            if slot.type in GOOGLE_TYPES and not (s.google_client_id and s.google_client_secret):
                needs.append("GOOGLE_CLIENT_ID/SECRET")
            if slot.source is CredentialSource.SHARED and slot.ref == "openai" and not s.openai_api_key:
                needs.append("OPENAI_API_KEY")
            if (
                slot.source is CredentialSource.SHARED
                and slot.ref == "reader"
                and not (s.reader_base_url and s.reader_api_token)
            ):
                needs.append("READER_BASE_URL/READER_API_TOKEN")
        return sorted(set(needs))

    # ------------------------------------------------------------------ deploy

    def deploy(self, ctx: DeployContext) -> DeployResult:
        entry = ctx.workflow
        if self._missing_config(entry):
            raise AdapterError(self.check_available(entry).reason or "Not set up on this server yet")
        spec = entry.n8n
        created = _Created()
        prefix = f"demo · {ctx.username} · {entry.id}"
        try:
            values = {name: self._value(ctx, name, source, created) for name, source in spec.values.items()}
            credentials = {}
            for slot_name, slot in spec.credentials.items():
                credentials[slot_name] = self._create_credential(
                    created, f"{prefix} · {slot_name}", slot.type, self._credential_data(ctx, slot)
                )
            hook = None
            if entry.run_now:
                path = str(uuid.uuid4())
                hook = RunHook(
                    path=path,
                    credential=self._create_credential(
                        created,
                        f"{prefix} · run now",
                        "httpHeaderAuth",
                        {"name": RUN_HEADER, "value": self._run_token(path)},
                    ),
                )
            workflow = build_workflow(
                load_template(entry),
                name=f"[demo] {entry.name} · {ctx.username}",
                values=values,
                credentials=credentials,
                run_hook=hook,
            )
            created.workflow_id = self._client.create_workflow(workflow)
            self._client.publish_workflow(created.workflow_id)
        except (N8nError, TransformError, google.GoogleError) as exc:
            self._cleanup(created)
            raise AdapterError(f"n8n deploy failed: {exc}") from None
        except Exception:
            self._cleanup(created)
            raise

        refs: dict[str, Any] = {
            "workflow_id": created.workflow_id,
            "credential_ids": created.credential_ids,
            "workflow_url": f"{self._client.base_url}/workflow/{created.workflow_id}",
        }
        if hook is not None:
            refs["webhook_path"] = hook.path
        if created.spreadsheet_id:
            refs["spreadsheet_id"] = created.spreadsheet_id
            refs["spreadsheet_url"] = created.spreadsheet_url
        return DeployResult(refs=refs, message="Deployed and published on n8n")

    def finish_user_step(self, ctx: DeployContext, params: dict[str, str]) -> DeployResult:
        raise AdapterError("n8n deployments have no popup step")

    def undeploy(self, ctx: DeployContext) -> None:
        refs = ctx.refs
        try:
            if refs.get("workflow_id"):
                self._client.delete_workflow(str(refs["workflow_id"]))  # also unpublishes
            for credential_id in refs.get("credential_ids") or []:
                self._client.delete_credential(str(credential_id))
        except N8nError as exc:
            raise AdapterError(f"Couldn't remove the n8n workflow: {exc}") from None

    # ------------------------------------------------------------------ runs

    def run_now(self, ctx: DeployContext) -> RunStarted:
        path = ctx.refs.get("webhook_path")
        if not path:
            raise AdapterError("This deployment has no Run now trigger; redeploy it")
        try:
            self._client.call_webhook(
                str(path), (RUN_HEADER, self._run_token(str(path))), {"source": "workflow-demo"}
            )
        except N8nError as exc:
            if exc.status_code == 404:
                raise AdapterError("n8n no longer has this workflow published; redeploy it") from None
            raise AdapterError(f"Couldn't start the run: {exc}") from None
        return RunStarted(
            run_id=None, message="Run started on n8n; the result appears below when it finishes"
        )

    def recent_runs(self, ctx: DeployContext, limit: int = 10) -> list[RunSummary]:
        workflow_id = ctx.refs.get("workflow_id")
        if not workflow_id:
            return []
        try:
            executions = self._client.executions(str(workflow_id), limit=limit)
        except N8nError as exc:
            raise AdapterError(f"Couldn't read runs from n8n: {exc}") from None
        result_nodes = ctx.workflow.n8n.result_nodes if ctx.workflow.n8n else []
        return [summarize_execution(e, result_nodes) for e in executions]

    # ------------------------------------------------------------------ helpers

    def _run_token(self, path: str) -> str:
        """Derived from a server secret, so it never needs storing."""
        return hmac.new(self._run_key, path.encode(), hashlib.sha256).hexdigest()

    def _create_credential(
        self, created: _Created, name: str, credential_type: str, data: dict[str, Any]
    ) -> CredentialRef:
        credential_id = self._client.create_credential(name, credential_type, data)
        created.credential_ids.append(credential_id)
        return CredentialRef(id=credential_id, name=name)

    def _value(self, ctx: DeployContext, name: str, source: ValueSource, created: _Created) -> Any:
        s = self._settings
        if source is ValueSource.SETTING:
            return ctx.settings.get(name, "")
        if source is ValueSource.SHARED:
            if name == "reader_url":
                return f"{(s.reader_base_url or '').rstrip('/')}/extract"
            if name == "llm_endpoint":
                return f"{s.openai_base_url.rstrip('/')}/chat/completions"
        if source is ValueSource.DEPLOY and name == "spreadsheet_id":
            return self._create_spreadsheet(ctx, created)
        raise AdapterError(f"Don't know how to provide {name!r} ({source.value})")

    def _create_spreadsheet(self, ctx: DeployContext, created: _Created) -> str:
        tokens = self._credentials(ctx).oauth_tokens("google")
        sites = [str(site) for site in ctx.settings.get("sites") or []]
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        sheet = google.create_uptime_sheet(
            self._http, tokens.access_token, f"Uptime monitor (demo) {stamp}", sites
        )
        created.spreadsheet_id, created.spreadsheet_url = sheet.id, sheet.url
        created.google_token = tokens.access_token
        return sheet.id

    def _credential_data(self, ctx: DeployContext, slot: CredentialSlot) -> dict[str, Any]:
        s = self._settings
        if slot.source is CredentialSource.SHARED:
            if slot.ref == "openai" and s.openai_api_key:
                return {"apiKey": s.openai_api_key.get_secret_value(), "url": s.openai_base_url.rstrip("/")}
            if slot.ref == "reader" and s.reader_api_token:
                return {"name": "Authorization", "value": f"Bearer {s.reader_api_token.get_secret_value()}"}
            raise AdapterError(f"Shared credential {slot.ref!r} isn't configured")
        credentials = self._credentials(ctx)
        if slot.type in GOOGLE_TYPES:
            tokens = credentials.oauth_tokens(slot.ref, with_refresh_token=True)
            token_data = {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": "Bearer",
            }
            if tokens.scope:
                token_data["scope"] = tokens.scope
            return {
                "clientId": s.google_client_id,
                "clientSecret": s.google_client_secret.get_secret_value() if s.google_client_secret else "",
                "oauthTokenData": token_data,
            }
        if slot.type == "slackApi":
            return {"accessToken": credentials.oauth_tokens(slot.ref).access_token}
        if slot.type == "httpHeaderAuth" and slot.ref in SECRET_HEADERS:
            return {"name": SECRET_HEADERS[slot.ref], "value": credentials.secret_value(slot.ref)}
        raise AdapterError(f"Don't know how to build a {slot.type} credential from {slot.ref}")

    @staticmethod
    def _credentials(ctx: DeployContext):
        if ctx.credentials is None:
            raise AdapterError("No access to your connections in this job")
        return ctx.credentials

    def _cleanup(self, created: _Created) -> None:
        try:
            if created.workflow_id:
                self._client.delete_workflow(created.workflow_id)
            for credential_id in created.credential_ids:
                self._client.delete_credential(credential_id)
        except N8nError:
            log.warning("couldn't clean up after a failed n8n deploy: %s", created, exc_info=True)
        if created.spreadsheet_id and created.google_token:
            google.delete_file(self._http, created.google_token, created.spreadsheet_id)


# ---------------------------------------------------------------------- results


def summarize_execution(execution: dict[str, Any], result_nodes: list[str]) -> RunSummary:
    result = _result_data(execution)
    lines: list[str] = []
    run_data = result.get("runData") if isinstance(result.get("runData"), dict) else {}
    for node_name in result_nodes:
        for run in run_data.get(node_name) or []:
            for item in _main_items(run):
                text = _item_text(item.get("json") if isinstance(item, dict) else None)
                if text:
                    lines.append(text)
    summary = "\n".join(lines)
    if len(summary) > MAX_SUMMARY:
        summary = summary[: MAX_SUMMARY - 1] + "…"
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    status = STATUS.get(str(execution.get("status")), "running")
    return RunSummary(
        id=str(execution.get("id")),
        status=status,
        started_at=_parse_time(execution.get("startedAt")),
        finished_at=_parse_time(execution.get("stoppedAt")),
        summary=summary or None,
        error=str(error.get("message"))[:500]
        if error.get("message")
        else ("Canceled" if execution.get("status") == "canceled" else None),
    )


def _result_data(execution: dict[str, Any]) -> dict[str, Any]:
    data = execution.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return {}
    if not isinstance(data, dict):
        return {}
    result = data.get("resultData")
    return result if isinstance(result, dict) else {}


def _main_items(run: Any) -> list[Any]:
    if not isinstance(run, dict):
        return []
    main = (run.get("data") or {}).get("main") if isinstance(run.get("data"), dict) else None
    if not isinstance(main, list) or not main or not isinstance(main[0], list):
        return []
    return main[0]


def _item_text(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("report", "text"):
        if isinstance(data.get(key), str) and data[key].strip():
            return data[key].strip()
    if "Property" in data:  # uptime monitor: one line per site
        if data.get("DOWN_FROM_UP"):
            state = "DOWN (alert sent)"
        elif data.get("DOWN_FROM_DOWN"):
            state = "still DOWN (alert sent)"
        elif data.get("UP_FROM_DOWN"):
            state = "back UP (alert sent)"
        else:
            state = "UP"
        return f"{data['Property']} is {state}"
    return None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
