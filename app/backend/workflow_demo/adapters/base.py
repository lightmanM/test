"""Interface every platform adapter (n8n, Make Bridge, Modal, fake) implements."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from workflow_demo.catalog.models import Platform, WorkflowEntry


class AdapterError(Exception):
    """A platform call failed; the message is shown to the user."""


@dataclass(frozen=True)
class ConnectionInfo:
    connector: str
    method: str  # nango | manual | fake
    details: dict[str, Any]
    nango_integration: str | None = None
    nango_connection_id: str | None = None


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    refresh_token: str | None = None
    scope: str | None = None


class SecretReader(Protocol):
    """Reads the user's secrets on demand, only inside deploy jobs (never stored in refs)."""

    def oauth_tokens(self, connector: str, *, with_refresh_token: bool = False) -> OAuthTokens: ...

    def secret_value(self, connector: str) -> str: ...


@dataclass(frozen=True)
class DeployContext:
    username: str
    workflow: WorkflowEntry
    deployment_id: int
    settings: dict[str, Any]
    connections: dict[str, ConnectionInfo]
    refs: dict[str, Any]  # platform IDs from the previous deploy (undeploy / runs / redeploy)
    # Set on deploy: signed one-time token and the URL the platform's popup must return to
    # (Make Bridge redirectUri). Valid only for this deploy attempt.
    user_step_state: str | None = None
    callback_url: str | None = None
    credentials: SecretReader | None = None
    # Refs of the deployment being replaced (redeploy only), e.g. to reuse the user's spreadsheet.
    previous_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class DeployResult:
    refs: dict[str, Any]
    # "awaiting_user": the user still has to finish a step on the platform (Make's popup at
    # refs["popup_url"]); the deployment becomes active through finish_user_step().
    status: Literal["active", "awaiting_user"] = "active"
    message: str = ""


@dataclass(frozen=True)
class RunStarted:
    run_id: str | None
    message: str
    refs_update: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunSummary:
    id: str
    status: str  # running | success | error | waiting
    started_at: datetime | None
    finished_at: datetime | None = None
    summary: str | None = None  # result text shown to the user
    error: str | None = None


class PlatformAdapter(Protocol):
    platform: Platform

    def check_available(self, entry: WorkflowEntry | None = None) -> Availability: ...

    def deploy(self, ctx: DeployContext) -> DeployResult: ...

    def finish_user_step(self, ctx: DeployContext, params: dict[str, str]) -> DeployResult: ...

    def undeploy(self, ctx: DeployContext) -> None: ...

    def run_now(self, ctx: DeployContext) -> RunStarted: ...

    def recent_runs(self, ctx: DeployContext, limit: int = 10) -> list[RunSummary]: ...
