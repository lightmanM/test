"""The shared Slack → Meegle bot (one Modal deployment for everyone): "Activate for me".

Nothing is deployed per tester. Activating records the tester's Slack user ID in the deployment's
refs; the bot looks testers up through ``/api/bot/user-map`` (answered from their current
connections while the activation is live) and reports created cards to ``/api/bot/cards`` (shown
as runs). Deactivating, the 24 h expiry or disconnecting Slack/Meegle ends the mapping.
"""

from __future__ import annotations

from workflow_demo.adapters.base import (
    AdapterError,
    Availability,
    DeployContext,
    DeployResult,
    RunStarted,
    RunSummary,
    runs_from_refs,
)
from workflow_demo.catalog.models import Platform, WorkflowEntry
from workflow_demo.config import Settings


class SharedBotAdapter:
    platform = Platform.MODAL

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check_available(self, entry: WorkflowEntry | None = None) -> Availability:
        if entry is not None and not (entry.modal and entry.modal.shared_deployment):
            return Availability(False, "Only the shared Slack bot runs on Modal in this demo")
        if not self._settings.bot_api_token:
            return Availability(False, "Not set up on this server yet (missing BOT_API_TOKEN)")
        return Availability(True)

    def deploy(self, ctx: DeployContext) -> DeployResult:
        available = self.check_available(ctx.workflow)
        if not available.available:
            raise AdapterError(available.reason or "Not available")
        slack = ctx.connections.get("slack")
        if slack is None:
            raise AdapterError("Connect Slack first")
        if slack.method != "nango":
            raise AdapterError("Slack was connected with demo data; connect it for real")
        slack_user_id = slack.details.get("slack_user_id")
        if not slack_user_id:
            raise AdapterError("Reconnect Slack: the demo didn't receive your Slack user ID")
        team = self._settings.slack_bot_team_id
        if team and slack.details.get("team_id") != team:
            raise AdapterError("Connect Slack in the workspace the bot is in, then activate again")
        if ctx.credentials is None:
            raise AdapterError("No access to your connections in this job")
        user_key = ctx.credentials.secret_value("meegle_user_key")
        return DeployResult(
            refs={
                "slack_user_id": slack_user_id,
                "meegle_user_key": user_key,
                "runs": list(ctx.previous_refs.get("runs") or []),  # keep card history on redeploy
            },
            message="Activated: mention the bot in Slack to create a card",
        )

    def finish_user_step(self, ctx: DeployContext, params: dict[str, str]) -> DeployResult:
        raise AdapterError("The bot has no popup step")

    def undeploy(self, ctx: DeployContext) -> None:
        return None  # the mapping ends with the active status

    def run_now(self, ctx: DeployContext) -> RunStarted:
        raise AdapterError("The bot runs when you mention it in Slack")

    def recent_runs(self, ctx: DeployContext, limit: int = 10) -> list[RunSummary]:
        return runs_from_refs(ctx.refs, limit)
