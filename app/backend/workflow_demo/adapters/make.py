"""GitHub merge → Slack on Make, through Make Bridge (testers connect accounts in Make's popup).

Deploy starts a Bridge integration and waits for the user (``awaiting_user`` with the popup URL);
Make redirects the popup to ``/make/callback``, where ``finish_user_step`` reads the created
scenario and activates it. Make holds the GitHub and Slack connections; the demo never sees them.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from workflow_demo.adapters.base import (
    AdapterError,
    Availability,
    DeployContext,
    DeployResult,
    RunStarted,
    RunSummary,
)
from workflow_demo.catalog.models import Platform, WorkflowEntry
from workflow_demo.config import Settings
from workflow_demo.make_bridge import BridgeClient, BridgeError

log = logging.getLogger(__name__)

AVAILABLE_TTL = 10 * 60  # seconds to trust an availability check
UNREACHABLE_TTL = 60
FINISH_ATTEMPTS = 5  # Make can redirect a moment before the flow reports completion
REQUIRED = ("make_bridge_key_id", "make_bridge_secret", "make_bridge_template_id")
LOG_STATUS = {1: "success", 2: "success", 3: "error"}  # 2 = finished with warnings


def subject(username: str) -> str:
    """The Bridge end user: one sandbox per demo user in the owner's account."""
    return f"workflow-demo:{username}"


class MakeBridgeAdapter:
    platform = Platform.MAKE

    def __init__(self, settings: Settings, http: httpx.Client) -> None:
        self._settings = settings
        missing = [name.upper() for name in REQUIRED if not getattr(settings, name, None)]
        self._missing = missing
        self._client = (
            None
            if missing
            else BridgeClient(
                settings.make_zone,
                settings.make_bridge_key_id,
                settings.make_bridge_secret.get_secret_value(),
                http,
                team_id=settings.make_team_id,
            )
        )
        self._availability: tuple[float, Availability] | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ availability

    def check_available(self, entry: WorkflowEntry | None = None) -> Availability:
        if self._client is None:
            return Availability(False, f"Not set up on this server yet (missing {', '.join(self._missing)})")
        with self._lock:
            cached = self._availability
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        ttl = AVAILABLE_TTL
        try:
            # Runs while the catalog loads, so keep it short.
            self._client.integrations(subject("setup-check"), timeout=5)
            result = Availability(True)
        except BridgeError as exc:
            if exc.status_code in (401, 403, 404):
                result = Availability(
                    False, "Deploy unavailable: Make Bridge isn't enabled for the owner's account"
                )
            else:
                result = Availability(False, f"Make is unreachable right now ({exc})")
                ttl = UNREACHABLE_TTL
        with self._lock:
            self._availability = (time.monotonic() + ttl, result)
        return result

    def _bridge(self) -> BridgeClient:
        if self._client is None:
            raise AdapterError(f"Not set up on this server yet (missing {', '.join(self._missing)})")
        return self._client

    # ------------------------------------------------------------------ deploy

    def deploy(self, ctx: DeployContext) -> DeployResult:
        if not ctx.callback_url:
            raise AdapterError("This deploy can't receive Make's popup result; try again")
        try:
            public_url, flow_id = self._bridge().init(
                subject(ctx.username),
                int(self._settings.make_bridge_template_id),
                ctx.callback_url,
                f"[demo] {ctx.workflow.name} · {ctx.username}",
            )
        except BridgeError as exc:
            raise AdapterError(f"Make deploy failed: {exc}") from None
        return DeployResult(
            refs={"popup_url": public_url, "flow_id": flow_id},
            status="awaiting_user",
            message="Waiting for you to connect GitHub and Slack in Make's popup",
        )

    def finish_user_step(self, ctx: DeployContext, params: dict[str, str]) -> DeployResult:
        flow_id = ctx.refs.get("flow_id")
        if not flow_id:
            raise AdapterError("This deployment has no Make setup in progress; deploy again")
        bridge, user = self._bridge(), subject(ctx.username)
        scenario_ids = self._wait_for_scenarios(bridge, user, str(flow_id))
        scenario_id = scenario_ids[0]
        try:
            bridge.activate(user, scenario_id)
        except BridgeError as exc:
            for created in scenario_ids:
                self._delete_quietly(bridge, user, created)
            raise AdapterError(f"Couldn't activate the Make scenario: {exc}") from None
        for extra in scenario_ids[1:]:  # the template has one scenario; never leave strays running
            self._delete_quietly(bridge, user, extra)
        return DeployResult(
            refs={"flow_id": flow_id, "scenario_id": scenario_id},
            message="Make scenario created and activated",
        )

    def _wait_for_scenarios(self, bridge: BridgeClient, user: str, flow_id: str) -> list[int]:
        flow: dict[str, Any] = {}
        for attempt in range(FINISH_ATTEMPTS):
            try:
                flow = bridge.check_init(user, flow_id)
            except BridgeError as exc:
                raise AdapterError(f"Couldn't read the Make setup: {exc}") from None
            if flow.get("isCompleted"):
                break
            if attempt < FINISH_ATTEMPTS - 1:
                time.sleep(1 + attempt)
        else:
            message = flow.get("statusMessage") or "not finished"
            raise AdapterError(
                f"Make setup isn't finished ({message}); finish it in the popup or deploy again"
            )
        scenarios = (flow.get("result") or {}).get("scenarios") or []
        ids = [int(s["id"]) for s in scenarios if isinstance(s, dict) and s.get("id") is not None]
        if not ids:
            raise AdapterError("Make finished without creating a scenario; deploy again")
        return ids

    def undeploy(self, ctx: DeployContext) -> None:
        bridge, user = self._bridge(), subject(ctx.username)
        scenario_ids = [ctx.refs["scenario_id"]] if ctx.refs.get("scenario_id") else []
        if not scenario_ids and ctx.refs.get("flow_id"):
            # The user finished in Make but the demo never heard back: remove what Make created.
            try:
                flow = bridge.check_init(user, str(ctx.refs["flow_id"]))
                scenarios = (
                    (flow.get("result") or {}).get("scenarios") or [] if flow.get("isCompleted") else []
                )
                scenario_ids = [int(s["id"]) for s in scenarios if isinstance(s, dict) and s.get("id")]
            except BridgeError:
                log.warning("couldn't check Make flow %s while undeploying", ctx.refs["flow_id"])
        for scenario_id in scenario_ids:
            try:
                bridge.deactivate(user, int(scenario_id))
            except BridgeError as exc:
                if exc.status_code != 404:
                    log.warning("couldn't deactivate Make scenario %s: %s", scenario_id, exc)
            try:
                bridge.delete(user, int(scenario_id))
            except BridgeError as exc:
                raise AdapterError(f"Couldn't remove the Make scenario: {exc}") from None

    @staticmethod
    def _delete_quietly(bridge: BridgeClient, user: str, scenario_id: int) -> None:
        try:
            bridge.delete(user, scenario_id)
        except BridgeError:
            log.warning("couldn't delete Make scenario %s", scenario_id, exc_info=True)

    # ------------------------------------------------------------------ runs

    def run_now(self, ctx: DeployContext) -> RunStarted:
        scenario_id = ctx.refs.get("scenario_id")
        if not scenario_id:
            raise AdapterError("This deployment has no Make scenario; redeploy it")
        try:
            execution_id = self._bridge().run(subject(ctx.username), int(scenario_id))
        except BridgeError as exc:
            raise AdapterError(f"Couldn't start the run: {exc}") from None
        return RunStarted(
            run_id=execution_id, message="Run started on Make; it appears below when it finishes"
        )

    def recent_runs(self, ctx: DeployContext, limit: int = 10) -> list[RunSummary]:
        scenario_id = ctx.refs.get("scenario_id")
        if not scenario_id:
            return []
        try:
            logs = self._bridge().logs(subject(ctx.username), int(scenario_id))
        except BridgeError as exc:
            raise AdapterError(f"Couldn't read runs from Make: {exc}") from None
        runs = [summarize_log(item) for item in logs if _is_execution(item)]
        return runs[:limit]


def _is_execution(item: dict[str, Any]) -> bool:
    event = str(item.get("eventType") or "")
    return item.get("status") in LOG_STATUS or "EXECUTION" in event.upper()


def summarize_log(item: dict[str, Any]) -> RunSummary:
    started = _time(item.get("timestamp"))
    duration = item.get("duration")
    finished = (
        started + timedelta(milliseconds=duration) if started and isinstance(duration, int | float) else None
    )
    status = LOG_STATUS.get(item.get("status"), "running")
    operations = item.get("operations")
    summary = (
        f"{operations} operation{'s' if operations != 1 else ''}" if isinstance(operations, int) else None
    )
    if item.get("status") == 2:
        summary = f"{summary or 'Finished'} (with warnings)"
    error = item.get("error")
    message = error.get("message") if isinstance(error, dict) else error if isinstance(error, str) else None
    return RunSummary(
        id=str(item.get("id") or item.get("imtId") or item.get("timestamp")),
        status=status,
        started_at=started,
        finished_at=finished,
        summary=summary,
        error=(message or "The run failed; see Make for details")[:500] if status == "error" else None,
    )


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
