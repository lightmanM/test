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
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
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
    OAuthTokens,
    RunStarted,
    RunSummary,
    SecretReader,
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


@dataclass(frozen=True)
class OwnerItem:
    """Something built from the owner's configuration: the settings it needs and how to build it."""

    needs: tuple[str, ...]  # Settings attribute names (also the env var names, upper-cased)
    build: Callable[[Settings], Any]


def _secret(value: Any) -> str:
    return value.get_secret_value() if value is not None else ""


# The catalog declares `shared` values / credentials by name; this is where each one comes from.
SHARED_VALUES: dict[str, OwnerItem] = {
    "reader_url": OwnerItem(("reader_base_url",), lambda s: f"{s.reader_base_url.rstrip('/')}/extract"),
    "llm_endpoint": OwnerItem((), lambda s: f"{s.openai_base_url.rstrip('/')}/chat/completions"),
}
SHARED_CREDENTIALS: dict[str, OwnerItem] = {
    "openai": OwnerItem(
        ("openai_api_key",),
        lambda s: {"apiKey": _secret(s.openai_api_key), "url": s.openai_base_url.rstrip("/")},
    ),
    "reader": OwnerItem(
        ("reader_base_url", "reader_api_token"),
        lambda s: {"name": "Authorization", "value": f"Bearer {_secret(s.reader_api_token)}"},
    ),
}
# Google credentials need our OAuth client so n8n can refresh the user's tokens.
GOOGLE_TYPES = {"googleSheetsOAuth2Api", "gmailOAuth2"}
GOOGLE_NEEDS = ("google_client_id", "google_client_secret")
# `deploy` values the adapter produces while deploying.
DEPLOY_VALUES = {"spreadsheet_id"}
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
FINAL = {"success", "error", "crashed", "canceled"}
MAX_SUMMARY = 4000


@dataclass
class _Created:
    """What a deploy created so far, removed again if a later step fails."""

    credential_ids: list[str] = field(default_factory=list)
    workflow_id: str | None = None
    spreadsheet_id: str | None = None  # only set when this deploy created it
    spreadsheet_url: str | None = None
    google_token: str | None = field(default=None, repr=False)


class _CachedSecrets:
    """One Nango read per connector per deploy (a refresh-token read also serves plain reads)."""

    def __init__(self, inner: SecretReader) -> None:
        self._inner = inner
        self._tokens: dict[str, OAuthTokens] = {}

    def oauth_tokens(self, connector: str, *, with_refresh_token: bool = False) -> OAuthTokens:
        cached = self._tokens.get(connector)
        if cached is None or (with_refresh_token and not cached.refresh_token):
            cached = self._inner.oauth_tokens(connector, with_refresh_token=with_refresh_token)
            self._tokens[connector] = cached
        return cached

    def secret_value(self, connector: str) -> str:
        return self._inner.secret_value(connector)


class N8nAdapter:
    platform = Platform.N8N

    def __init__(self, settings: Settings, client: N8nClient, http: httpx.Client) -> None:
        self._settings = settings
        self._client = client
        self._http = http
        self._run_key = hashlib.sha256(
            b"n8n-run:" + settings.session_secret.get_secret_value().encode()
        ).digest()
        # Finished executions never change: summarize each once (bounded, per process).
        self._summaries: OrderedDict[str, RunSummary] = OrderedDict()
        self._summaries_lock = threading.Lock()

    # ------------------------------------------------------------------ availability

    def check_available(self, entry: WorkflowEntry | None = None) -> Availability:
        missing = self.missing_config(entry) if entry is not None else []
        if missing:
            return Availability(False, f"Not set up on this server yet (missing {', '.join(missing)})")
        return Availability(True)

    def missing_config(self, entry: WorkflowEntry) -> list[str]:
        spec = entry.n8n
        if spec is None:
            return ["n8n template"]
        needs: set[str] = set()
        problems: set[str] = set()
        for name, source in spec.values.items():
            if source is ValueSource.SHARED:
                item = SHARED_VALUES.get(name)
                needs.update(item.needs if item else ())
                if item is None:
                    problems.add(f"support for shared value {name!r}")
            elif source is ValueSource.DEPLOY and name not in DEPLOY_VALUES:
                problems.add(f"support for deploy value {name!r}")
            elif source is ValueSource.CONNECTION:
                problems.add(f"support for connection value {name!r}")
        for slot in spec.credentials.values():
            if slot.source is CredentialSource.SHARED:
                item = SHARED_CREDENTIALS.get(slot.ref)
                needs.update(item.needs if item else ())
                if item is None:
                    problems.add(f"support for shared credential {slot.ref!r}")
            elif slot.type in GOOGLE_TYPES:
                needs.update(GOOGLE_NEEDS)
            elif slot.type == "httpHeaderAuth" and slot.ref not in SECRET_HEADERS:
                problems.add(f"support for a {slot.ref} header credential")
            elif slot.type not in GOOGLE_TYPES | {"slackApi", "httpHeaderAuth"}:
                problems.add(f"support for {slot.type} credentials")
        unset = {name.upper() for name in needs if not getattr(self._settings, name, None)}
        return sorted(unset) + sorted(problems)

    # ------------------------------------------------------------------ deploy

    def deploy(self, ctx: DeployContext) -> DeployResult:
        entry = ctx.workflow
        missing = self.missing_config(entry)
        if missing:
            raise AdapterError(f"Not set up on this server yet (missing {', '.join(missing)})")
        spec = entry.n8n
        secrets = _CachedSecrets(self._secrets(ctx))
        created = _Created()
        prefix = f"demo · {ctx.username} · {entry.id}"
        sheet: dict[str, str] = {}
        try:
            values = {}
            for name, source in spec.values.items():
                if source is ValueSource.SETTING:
                    values[name] = ctx.settings.get(name, "")
                elif source is ValueSource.SHARED:
                    values[name] = SHARED_VALUES[name].build(self._settings)
                else:  # DEPLOY: spreadsheet_id (checked by missing_config)
                    sheet = self._spreadsheet(ctx, secrets, created)
                    values[name] = sheet["spreadsheet_id"]
            credentials = {}
            for slot_name, slot in spec.credentials.items():
                credentials[slot_name] = self._create_credential(
                    created, f"{prefix} · {slot_name}", slot.type, self._credential_data(slot, secrets)
                )
            hook = None
            if entry.run_now:
                path = str(uuid.uuid4())
                run_credential = self._create_credential(
                    created,
                    f"{prefix} · run now",
                    "httpHeaderAuth",
                    {"name": RUN_HEADER, "value": self._run_token(path)},
                )
                hook = RunHook(path=path, credential=run_credential)
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
            **sheet,
        }
        if hook is not None:
            refs["webhook_path"] = hook.path
        return DeployResult(refs=refs, message="Deployed and published on n8n")

    def finish_user_step(self, ctx: DeployContext, params: dict[str, str]) -> DeployResult:
        raise AdapterError("n8n deployments have no popup step")

    def undeploy(self, ctx: DeployContext) -> None:
        """Remove the workflow and its credentials. The user's spreadsheet stays in their Drive."""
        refs = ctx.refs
        failures = self._delete_all(refs.get("workflow_id"), refs.get("credential_ids") or [])
        if failures:
            raise AdapterError(f"Couldn't remove everything from n8n: {failures[0]}")

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
        result_nodes = ctx.workflow.n8n.result_nodes if ctx.workflow.n8n else []
        try:
            return [
                self._summary(e, result_nodes) for e in self._client.executions(str(workflow_id), limit=limit)
            ]
        except N8nError as exc:
            raise AdapterError(f"Couldn't read runs from n8n: {exc}") from None

    def _summary(self, listed: dict[str, Any], result_nodes: list[str]) -> RunSummary:
        """Summaries need the execution's data: fetched once, when the execution has finished."""
        execution_id = str(listed.get("id"))
        if listed.get("status") not in FINAL:
            return summarize_execution(listed, result_nodes)
        with self._summaries_lock:
            cached = self._summaries.get(execution_id)
        if cached is not None:
            return cached
        summary = summarize_execution(self._client.execution(execution_id), result_nodes)
        with self._summaries_lock:
            self._summaries[execution_id] = summary
            while len(self._summaries) > 500:
                self._summaries.popitem(last=False)
        return summary

    # ------------------------------------------------------------------ helpers

    def _run_token(self, path: str) -> str:
        """Derived from a server secret, so it never needs storing."""
        return hmac.new(self._run_key, path.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _secrets(ctx: DeployContext) -> SecretReader:
        if ctx.credentials is None:
            raise AdapterError("No access to your connections in this job")
        return ctx.credentials

    def _create_credential(
        self, created: _Created, name: str, credential_type: str, data: dict[str, Any]
    ) -> CredentialRef:
        credential_id = self._client.create_credential(name, credential_type, data)
        created.credential_ids.append(credential_id)
        return CredentialRef(id=credential_id, name=name)

    def _spreadsheet(self, ctx: DeployContext, secrets: SecretReader, created: _Created) -> dict[str, str]:
        """Reuse the previous deployment's spreadsheet on redeploy (keeps the user's Sites edits);
        otherwise create one seeded from the ``sites`` setting."""
        tokens = secrets.oauth_tokens("google", with_refresh_token=True)
        previous = ctx.previous_refs.get("spreadsheet_id")
        if previous:
            url = google.spreadsheet_url(self._http, tokens.access_token, str(previous))
            if url:
                return {"spreadsheet_id": str(previous), "spreadsheet_url": url}
        sites = [str(site) for site in ctx.settings.get("sites") or []]
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        sheet = google.create_uptime_sheet(
            self._http, tokens.access_token, f"Uptime monitor (demo) {stamp}", sites
        )
        created.spreadsheet_id, created.spreadsheet_url = sheet.id, sheet.url
        created.google_token = tokens.access_token
        return {"spreadsheet_id": sheet.id, "spreadsheet_url": sheet.url}

    def _credential_data(self, slot: CredentialSlot, secrets: SecretReader) -> dict[str, Any]:
        s = self._settings
        if slot.source is CredentialSource.SHARED:
            return SHARED_CREDENTIALS[slot.ref].build(s)
        if slot.type in GOOGLE_TYPES:
            tokens = secrets.oauth_tokens(slot.ref, with_refresh_token=True)
            token_data = {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": "Bearer",
            }
            if tokens.scope:
                token_data["scope"] = tokens.scope
            return {
                "clientId": s.google_client_id,
                "clientSecret": _secret(s.google_client_secret),
                "oauthTokenData": token_data,
            }
        if slot.type == "slackApi":
            return {"accessToken": secrets.oauth_tokens(slot.ref).access_token}
        if slot.type == "httpHeaderAuth":
            return {"name": SECRET_HEADERS[slot.ref], "value": secrets.secret_value(slot.ref)}
        raise AdapterError(f"Don't know how to build a {slot.type} credential")  # missing_config reports it

    def _delete_all(self, workflow_id: Any, credential_ids: list[Any]) -> list[str]:
        """Delete each item independently, so one failure doesn't strand the rest."""
        failures = []
        if workflow_id:
            try:
                self._client.delete_workflow(str(workflow_id))  # also unpublishes
            except N8nError as exc:
                failures.append(f"workflow {workflow_id}: {exc}")
        for credential_id in credential_ids:
            try:
                self._client.delete_credential(str(credential_id))
            except N8nError as exc:
                failures.append(f"credential {credential_id}: {exc}")
        return failures

    def _cleanup(self, created: _Created) -> None:
        failures = self._delete_all(created.workflow_id, created.credential_ids)
        if failures:
            # IDs only: the names identify the user and workflow, and nothing secret is logged.
            log.warning("couldn't clean up after a failed n8n deploy: %s", "; ".join(failures))
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
    message = str(error["message"])[:500] if error.get("message") else None
    if message is None and execution.get("status") == "canceled":
        message = "Canceled"
    return RunSummary(
        id=str(execution.get("id")),
        status=STATUS.get(str(execution.get("status")), "running"),
        started_at=_parse_time(execution.get("startedAt")),
        finished_at=_parse_time(execution.get("stoppedAt")),
        summary=summary or None,
        error=message,
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
    if not isinstance(run, dict) or not isinstance(run.get("data"), dict):
        return []
    main = run["data"].get("main")
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
