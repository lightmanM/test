"""Fake adapters: the whole demo works end to end without platform credentials.

Used in development (``DEMO_FAKE_PLATFORMS=1``) and tests. Runs are kept in the deployment's
platform refs so they survive restarts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from workflow_demo.adapters.base import (
    Availability,
    DeployContext,
    DeployResult,
    RunStarted,
    RunSummary,
    runs_from_refs,
)
from workflow_demo.catalog.models import Platform

FAKE_RESULTS = {
    "uptime-monitor": "https://example.com is UP · https://httpbin.org/status/503 is DOWN (alert sent)",
    "meegle-daily-digest": "📊 研发日报（演示数据）: bug 6 (4 new, 2 closed), 3 stories in progress",
    "medium-digest": "Medium weekly report (demo data): 2 of 5 articles relevant — LLM agents, open source",
    "github-merge-slack": "Posted the diff of PR #12 (merged 2 minutes ago) to Slack",
    "slack-meegle-bot": "Created card “Fix login page error” (demo data)",
}


class FakeAdapter:
    def __init__(self, platform: Platform, popup_url_builder=None) -> None:
        self.platform = platform
        self._popup_url = popup_url_builder

    def check_available(self, entry=None) -> Availability:
        return Availability(True)

    def deploy(self, ctx: DeployContext) -> DeployResult:
        refs: dict[str, Any] = {"fake_id": f"fake-{ctx.workflow.id}-{ctx.deployment_id}", "runs": []}
        if ctx.workflow.modal and ctx.workflow.modal.shared_deployment:
            # What the real bot adapter records, so /api/bot/* works in fake mode too.
            slack = ctx.connections.get("slack")
            user_key = ctx.connections.get("meegle_user_key")
            refs["slack_user_id"] = slack.details.get("slack_user_id") if slack else None
            refs["meegle_user_key"] = user_key.details.get("value") if user_key else None
            refs["runs"] = list(ctx.previous_refs.get("runs") or [])
        if self.platform is Platform.MAKE and self._popup_url is not None and ctx.user_step_state:
            return DeployResult(
                refs={**refs, "popup_url": self._popup_url(ctx.user_step_state)},
                status="awaiting_user",
                message="Waiting for you to connect GitHub and Slack in Make's popup",
            )
        return DeployResult(refs=refs, message=f"Deployed to {self.platform.value} (fake)")

    def finish_user_step(self, ctx: DeployContext, params: dict[str, str]) -> DeployResult:
        refs = {k: v for k, v in ctx.refs.items() if k != "popup_url"}
        return DeployResult(refs=refs, message="Make connections completed (fake)")

    def undeploy(self, ctx: DeployContext) -> None:
        return None

    def run_now(self, ctx: DeployContext) -> RunStarted:
        runs = list(ctx.refs.get("runs", []))
        now = datetime.now(UTC)
        run = {
            "id": f"run-{len(runs) + 1}",
            "status": "success",
            "started_at": now.isoformat(),
            "finished_at": (now + timedelta(seconds=2)).isoformat(),
            "summary": FAKE_RESULTS.get(ctx.workflow.id, "Run finished (fake)"),
        }
        return RunStarted(
            run_id=run["id"], message="Run started (fake)", refs_update={"runs": [run, *runs][:20]}
        )

    def recent_runs(self, ctx: DeployContext, limit: int = 10) -> list[RunSummary]:
        return runs_from_refs(ctx.refs, limit)
