"""API response and request models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(max_length=100)
    passcode: str = Field(max_length=200)


class AdminLoginRequest(BaseModel):
    passcode: str = Field(max_length=200)


class Me(BaseModel):
    username: str


class ConnectorStatus(BaseModel):
    id: str
    name: str
    kind: str
    description: str
    purpose: str
    help: str | None = None
    connected: bool
    label: str | None = None  # e.g. the Slack workspace or Google email; never a secret
    secret: bool = False  # manual connectors: the value is hidden once saved
    managed_by_platform: bool  # connected inside the platform's popup, not in the demo


class SettingOut(BaseModel):
    key: str
    label: str
    type: str
    required: bool
    default: Any = None
    help: str | None = None
    options: list[Any] | None = None


class EventOut(BaseModel):
    at: datetime
    type: str
    message: str


class Link(BaseModel):
    label: str
    url: str


class DeploymentOut(BaseModel):
    workflow_id: str
    status: str
    settings: dict[str, Any]
    error: str | None
    deployed_at: datetime | None
    expires_at: datetime | None
    popup_url: str | None
    links: list[Link] = []  # things the deployment created for the user, e.g. their spreadsheet
    updated_at: datetime
    events: list[EventOut] = []


class WorkflowSummary(BaseModel):
    id: str
    name: str
    summary: str
    platform: str
    available: bool
    unavailable_reason: str | None
    ready: bool  # all demo-held connectors are connected
    connectors: list[ConnectorStatus]
    deployment: DeploymentOut | None


class WorkflowDetail(WorkflowSummary):
    description: str
    settings: list[SettingOut]
    try_it: str
    run_now: bool
    shared_deployment: bool


class DeployRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class RunStartedOut(BaseModel):
    run_id: str | None
    message: str


class RunOut(BaseModel):
    id: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    summary: str | None
    error: str | None


class ConnectionOut(BaseModel):
    connector: str
    name: str
    method: str
    status: str
    details: dict[str, Any]
    updated_at: datetime
