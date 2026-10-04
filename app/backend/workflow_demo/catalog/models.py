"""Schema for ``catalog/connectors.yaml`` and ``catalog/<workflow>/catalog.yaml``."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Platform(StrEnum):
    N8N = "n8n"
    MAKE = "make"
    MODAL = "modal"


class ConnectorKind(StrEnum):
    NANGO = "nango"  # OAuth popup run by Nango; tokens stored in Nango
    MANUAL = "manual"  # text box in the demo; stored encrypted in our DB
    PLATFORM_POPUP = "platform_popup"  # connected inside the platform's own popup (Make Bridge)


class Connector(Strict):
    id: str
    name: str
    kind: ConnectorKind
    description: str
    integration: str | None = None  # Nango integration key (kind=nango)
    secret: bool = False  # manual connectors: hide the value after saving
    help: str | None = None  # how to obtain the value (manual connectors)


class SettingType(StrEnum):
    STRING = "string"
    NUMBER = "number"
    SELECT = "select"
    URL_LIST = "url_list"
    SLACK_CHANNEL = "slack_channel"


class Setting(Strict):
    key: str
    label: str
    type: SettingType
    required: bool = True
    default: Any = None
    help: str | None = None
    options: list[Any] | None = None  # for type=select


class ValueSource(StrEnum):
    SETTING = "setting"  # from the user's settings form
    SHARED = "shared"  # from owner-provided configuration (e.g. reader URL)
    CONNECTION = "connection"  # derived from a connection (e.g. Slack incoming-webhook URL)
    DEPLOY = "deploy"  # produced during the deploy job (e.g. the created spreadsheet ID)


class CredentialSource(StrEnum):
    CONNECTION = "connection"  # built from the user's connection
    SHARED = "shared"  # one credential shared by every deployment (owner-provided key)


class CredentialSlot(Strict):
    type: str  # n8n credential type, e.g. googleSheetsOAuth2Api
    source: CredentialSource
    ref: str  # connector id (source=connection) or shared credential key (source=shared)


class WorkflowConnector(Strict):
    id: str
    purpose: str


class N8nSpec(Strict):
    template: str = "workflow.json"
    values: dict[str, ValueSource] = Field(default_factory=dict)
    credentials: dict[str, CredentialSlot] = Field(default_factory=dict)
    result_nodes: list[str] = Field(default_factory=list)  # nodes whose output is shown as the run result


class MakeSpec(Strict):
    blueprint: str = "blueprint.json"
    setup_doc: str = "make-setup.md"


class ModalSpec(Strict):
    service: str  # folder under services/
    shared_deployment: bool = True


class WorkflowEntry(Strict):
    id: str
    name: str
    summary: str
    description: str
    platform: Platform
    source: str  # path of the team's original, relative to the repo root
    connectors: list[WorkflowConnector]
    settings: list[Setting] = Field(default_factory=list)
    try_it: str
    run_now: bool = True
    # Shown to testers when the server lists this workflow in DISABLED_WORKFLOWS.
    unavailable_note: str | None = None
    n8n: N8nSpec | None = None
    make: MakeSpec | None = None
    modal: ModalSpec | None = None


class Catalog(Strict):
    connectors: dict[str, Connector]
    workflows: list[WorkflowEntry]

    def workflow(self, workflow_id: str) -> WorkflowEntry:
        for wf in self.workflows:
            if wf.id == workflow_id:
                return wf
        raise KeyError(workflow_id)
