"""GitHub merge → Slack on Make, through Make Bridge (testers connect accounts in Make's popup).

Deploy starts a Bridge integration and waits for the user (``awaiting_user`` with the popup URL).
Make redirects the popup to ``/make/callback``, which queues a job: ``finish_user_step`` waits
for Make to report the created scenario and activates it. Make holds the GitHub and Slack
connections; the demo never sees them.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from workflow_demo.adapters.base import (
    AdapterError,
    Availability,
    DeployContext,
    DeploymentSnapshot,
    DeployResult,
    OrphanReport,
    RunStarted,
    RunSummary,
)
from workflow_demo.catalog.models import Platform, WorkflowEntry
from workflow_demo.config import Settings
from workflow_demo.make_bridge import BridgeClient, BridgeError

log = logging.getLogger(__name__)

AVAILABLE_TTL = 10 * 60  # seconds to trust an availability check
RETRY_TTL = 60  # after an error that may go away (network, credentials being fixed)
# Make can redirect the popup a little before the flow reports completion: wait up to ~2 minutes.
FINISH_DELAYS = (1, 2, 3, 5, 5, 8, 8, 13, 13, 21, 21, 21)
REQUIRED = ("make_bridge_key_id", "make_bridge_secret", "make_bridge_template_id")
LOG_STATUS = {1: "success", 2: "success", 3: "error"}  # 2 = finished with warnings
IN_FLIGHT = {"deploying", "redeploying", "awaiting_user", "stopping"}
RECENT_USERS = timedelta(days=2)  # orphan sweep: users with Make activity this recent


def subject(username: str) -> str:
    """The Bridge end user: one sandbox per demo user in the owner's account."""
    return f"workflow-demo:{username}"


def scenario_name(entry: WorkflowEntry, username: str) -> str:
    return f"[demo] {entry.name} · {username}"


def scenario_ids(flow: dict[str, Any]) -> list[int]:
    """Scenario IDs from a completed ``check-init`` flow (invalid entries skipped)."""
    if not flow.get("isCompleted"):
        return []
    ids = []
    for scenario in (flow.get("result") or {}).get("scenarios") or []:
        try:
            ids.append(int(scenario["id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return ids


def _transient(exc: BridgeError) -> bool:
    return exc.status_code is None or exc.status_code >= 500 or exc.status_code == 429


class MakeBridgeAdapter:
    platform = Platform.MAKE

    def __init__(self, settings: Settings, http: httpx.Client) -> None:
        self._settings = settings
        self._missing = [name.upper() for name in REQUIRED if not getattr(settings, name, None)]
        self._client = (
            None
            if self._missing
            else BridgeClient(
                settings.make_zone,
                settings.make_bridge_key_id,
                settings.make_bridge_secret.get_secret_value(),
                http,
                team_id=settings.make_team_id,
            )
        )
        self._availability: tuple[float, Availability] | None = None
        self._refresh = threading.Lock()  # one availability check at a time

    # ------------------------------------------------------------------ availability

    def check_available(self, entry: WorkflowEntry | None = None) -> Availability:
        if self._client is None:
            return Availability(False, f"Not set up on this server yet (missing {', '.join(self._missing)})")
        cached = self._availability
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        with self._refresh:
            cached = self._availability  # another request may have refreshed it meanwhile
            if cached and time.monotonic() < cached[0]:
                return cached[1]
            result, ttl = self._probe(self._client)
            self._availability = (time.monotonic() + ttl, result)
            return result

    @staticmethod
    def _probe(client: BridgeClient) -> tuple[Availability, int]:
        try:
            # Runs while the catalog loads, so keep it short. Any 2xx answer means Bridge works.
            client.ping(subject("setup-check"), timeout=5)
        except BridgeError as exc:
            if exc.status_code == 401:
                reason = "Make rejected the demo's Bridge key (check MAKE_BRIDGE_KEY_ID / MAKE_BRIDGE_SECRET)"
                return Availability(False, f"Deploy unavailable: {reason}"), RETRY_TTL
            if exc.status_code in (403, 404):
                reason = "Make Bridge isn't enabled for the owner's account"
                return Availability(False, f"Deploy unavailable: {reason}"), AVAILABLE_TTL
            return Availability(False, f"Make is unreachable right now ({exc})"), RETRY_TTL
        return Availability(True), AVAILABLE_TTL

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
                scenario_name(ctx.workflow, ctx.username),
            )
        except BridgeError as exc:
            raise AdapterError(f"Make deploy failed: {exc}") from None
        return DeployResult(
            refs={"popup_url": public_url, "flow_id": flow_id},
            status="awaiting_user",
            message="Waiting for you to connect GitHub and Slack in Make's popup",
        )

    def finish_user_step(self, ctx: DeployContext, params: dict[str, str]) -> DeployResult:
        """Runs in a job after the popup came back: wait for the scenario, activate it."""
        flow_id = ctx.refs.get("flow_id")
        if not flow_id:
            raise AdapterError("This deployment has no Make setup in progress; deploy again")
        bridge, user = self._bridge(), subject(ctx.username)
        created = self._wait_for_scenarios(bridge, user, str(flow_id))
        scenario_id = created[0]
        try:
            bridge.activate(user, scenario_id)
        except BridgeError as exc:
            for other in created:
                self._delete_quietly(bridge, user, other)
            raise AdapterError(f"Couldn't activate the Make scenario: {exc}") from None
        for extra in created[1:]:  # the template has one scenario; never leave strays running
            self._delete_quietly(bridge, user, extra)
        # Also remove leftovers from popups abandoned earlier (Make can't cancel a started flow,
        # so a stale popup may still have finished and created a scenario).
        self._remove_strays(bridge, user, scenario_name(ctx.workflow, ctx.username), keep={scenario_id})
        return DeployResult(
            refs={"flow_id": flow_id, "scenario_id": scenario_id},
            message="Make scenario created and activated",
        )

    def _wait_for_scenarios(self, bridge: BridgeClient, user: str, flow_id: str) -> list[int]:
        flow: dict[str, Any] = {}
        for delay in (*FINISH_DELAYS, None):
            try:
                flow = bridge.check_init(user, flow_id)
            except BridgeError as exc:
                if not _transient(exc) or delay is None:
                    raise AdapterError(f"Couldn't read the Make setup: {exc}") from None
            else:
                if flow.get("isCompleted"):
                    ids = scenario_ids(flow)
                    if not ids:
                        raise AdapterError("Make finished without creating a scenario; deploy again")
                    return ids
            if delay is not None:
                time.sleep(delay)
        message = flow.get("statusMessage") or "not finished"
        raise AdapterError(f"Make setup isn't finished ({message}); deploy again to restart it")

    def undeploy(self, ctx: DeployContext) -> None:
        bridge, user = self._bridge(), subject(ctx.username)
        targets = []
        if ctx.refs.get("scenario_id"):
            targets.append(int(ctx.refs["scenario_id"]))
        elif ctx.refs.get("flow_id"):
            # The user may have finished in Make while the demo never heard back.
            try:
                targets = scenario_ids(bridge.check_init(user, str(ctx.refs["flow_id"])))
            except BridgeError:
                log.warning("couldn't check Make flow %s while undeploying", ctx.refs["flow_id"])
        for scenario_id in targets:
            try:
                bridge.deactivate(user, scenario_id)
            except BridgeError as exc:
                if exc.status_code != 404:
                    log.warning("couldn't deactivate Make scenario %s: %s", scenario_id, exc)
            try:
                bridge.delete(user, scenario_id)
            except BridgeError as exc:
                raise AdapterError(f"Couldn't remove the Make scenario: {exc}") from None
        self._remove_strays(bridge, user, scenario_name(ctx.workflow, ctx.username), keep=set())

    def _remove_strays(self, bridge: BridgeClient, user: str, name: str, keep: set[int]) -> None:
        """Best effort: delete this user's scenarios for this workflow that the demo doesn't track."""
        try:
            listed = self._scenarios(bridge, user)
        except AdapterError:
            log.warning("couldn't list Make integrations for cleanup", exc_info=True)
            return
        for scenario_id, scenario_name_ in listed:
            if scenario_name_ == name and scenario_id not in keep:
                self._delete_quietly(bridge, user, scenario_id)

    @staticmethod
    def _scenarios(bridge: BridgeClient, user: str) -> list[tuple[int, str]]:
        """``(id, name)`` of the scenarios in this user's Bridge sandbox."""
        try:
            integrations = bridge.integrations(user)
        except BridgeError as exc:
            raise AdapterError(f"Couldn't list Make integrations: {exc}") from None
        found = []
        for item in integrations:
            scenario = item.get("scenario") if isinstance(item, dict) else None
            if not isinstance(scenario, dict):
                continue
            try:
                found.append((int(scenario["id"]), str(scenario.get("name") or "")))
            except (KeyError, TypeError, ValueError):
                continue
        return found

    @staticmethod
    def _delete_quietly(bridge: BridgeClient, user: str, scenario_id: int) -> bool:
        try:
            bridge.delete(user, scenario_id)
        except BridgeError:
            log.warning("couldn't delete Make scenario %s", scenario_id, exc_info=True)
            return False
        return True

    # ------------------------------------------------------------------ orphan sweep

    def sweep_orphans(
        self,
        deployments: list[DeploymentSnapshot],
        older_than: datetime,
        current: Callable[[str], list[DeploymentSnapshot]] | None = None,
    ) -> OrphanReport:
        """Delete demo scenarios in users' Bridge sandboxes that their deployments don't track.

        Only users with Make activity in the last two days (older ones were swept already), one
        listing per user, and never while one of their Make deployments is mid-flight — re-checked
        with ``current(username)`` right before each delete, since a popup can finish meanwhile."""
        report = OrphanReport()
        if self._client is None:
            return report
        recent = older_than - RECENT_USERS
        users = sorted({d.username for d in deployments if _is_make(d) and d.updated_at >= recent})
        for username in users:
            user = subject(username)
            try:
                listed = self._scenarios(self._client, user)
            except AdapterError as exc:
                report.errors.append(f"Make ({username}): {exc}")
                continue
            for scenario_id, name in listed:
                fresh = current(username) if current else [d for d in deployments if d.username == username]
                if not _untracked(scenario_id, name, username, fresh):
                    continue
                if self._delete_quietly(self._client, user, scenario_id):
                    report.removed.append(f"Make scenario {scenario_id} ({username})")
                else:
                    report.errors.append(f"Make scenario {scenario_id} ({username}): delete failed")
        return report

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
        # Only finished executions carry a status; other log events (edits, starts) are skipped.
        return [summarize_log(item) for item in logs if item.get("status") in LOG_STATUS][:limit]


def _is_make(dep: DeploymentSnapshot) -> bool:
    return dep.workflow is not None and dep.workflow.platform is Platform.MAKE


def _untracked(scenario_id: int, name: str, username: str, deployments: list[DeploymentSnapshot]) -> bool:
    """A scenario with one of this user's demo names that none of their Make deployments uses."""
    mine = [d for d in deployments if d.username == username and _is_make(d)]
    if any(d.status in IN_FLIGHT for d in mine):
        return False
    if name not in {scenario_name(d.workflow, username) for d in mine}:
        return False
    tracked = set()
    for dep in mine:
        try:
            tracked.add(int(dep.refs["scenario_id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return scenario_id not in tracked


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
