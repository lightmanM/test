"""Turn a catalog template into the workflow one user deploys.

Fills ``__VALUE:<name>__`` placeholders, points credential slots at the credentials created for
the deployment, adds a header-authenticated Webhook trigger for "Run now", and keeps only the
fields n8n's create-workflow API accepts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from workflow_demo.catalog.loader import VALUE_PATTERN
from workflow_demo.n8n import workflow_json as wj

RUN_NODE_NAME = "Run now (demo)"
RUN_HEADER = "X-Demo-Run-Token"
TRIGGER_TYPES = ("n8n-nodes-base.scheduleTrigger", "n8n-nodes-base.manualTrigger")

# Fields the public API accepts on a node / in settings (strict schema; anything else is a 400).
NODE_KEYS = {
    "id",
    "name",
    "webhookId",
    "disabled",
    "notesInFlow",
    "notes",
    "type",
    "typeVersion",
    "executeOnce",
    "alwaysOutputData",
    "retryOnFail",
    "maxTries",
    "waitBetweenTries",
    "continueOnFail",
    "onError",
    "position",
    "parameters",
    "credentials",
}
SETTINGS_KEYS = {
    "saveExecutionProgress",
    "saveManualExecutions",
    "saveDataErrorExecution",
    "saveDataSuccessExecution",
    "executionTimeout",
    "errorWorkflow",
    "timezone",
    "executionOrder",
    "binaryMode",
    "callerPolicy",
}
# Keep every execution's data: the demo reads results from it.
DEMO_SETTINGS = {
    "executionOrder": "v1",
    "saveDataSuccessExecution": "all",
    "saveDataErrorExecution": "all",
    "saveManualExecutions": True,
}


class TransformError(ValueError):
    pass


@dataclass(frozen=True)
class CredentialRef:
    id: str
    name: str


@dataclass(frozen=True)
class RunHook:
    path: str  # unique webhook path, also used as the node's webhookId
    credential: CredentialRef  # httpHeaderAuth checked by the Webhook node


def build_workflow(
    template: dict[str, Any],
    *,
    name: str,
    values: dict[str, Any],
    credentials: dict[str, CredentialRef],
    run_hook: RunHook | None,
) -> dict[str, Any]:
    wf = wj.as_template(template, name)
    wf["nodes"] = _substitute(wf["nodes"], values)
    _wire_credentials(wf, credentials)
    if run_hook is not None:
        _add_run_hook(wf, run_hook)
    wf["nodes"] = [_clean_node(n) for n in wf["nodes"]]
    settings = {**(template.get("settings") or {}), **DEMO_SETTINGS}
    wf["settings"] = {k: v for k, v in settings.items() if k in SETTINGS_KEYS}
    return wf


def _substitute(value: Any, values: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: _substitute(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, values) for v in value]
    if not isinstance(value, str) or "__VALUE:" not in value:
        return value
    match = VALUE_PATTERN.fullmatch(value)
    if match is None:
        raise TransformError("a placeholder must be a whole parameter value")
    key = match.group(1)
    if key not in values:
        raise TransformError(f"no value for {key!r}")
    filled = values[key]
    # n8n evaluates a parameter starting with "=" as an expression; user input must stay literal.
    if isinstance(filled, str) and filled.startswith("="):
        raise TransformError(f"{key} can't start with '='")
    return filled


def _wire_credentials(wf: dict[str, Any], credentials: dict[str, CredentialRef]) -> None:
    for node_name, credential_type, slot in wj.credential_slots(wf):
        ref = credentials.get(slot)
        if ref is None:
            raise TransformError(f"no credential for slot {slot!r} (node {node_name!r})")
        wj.node(wf, node_name)["credentials"][credential_type] = {"id": ref.id, "name": ref.name}


def _add_run_hook(wf: dict[str, Any], hook: RunHook) -> None:
    triggers = [n for n in wf["nodes"] if n["type"] in TRIGGER_TYPES]
    entry: list[tuple[str, int]] = []
    for trigger in triggers:
        for _, edge in wj.edges_from(wf, trigger["name"], output=0):
            if (edge["node"], edge.get("index", 0)) not in entry:
                entry.append((edge["node"], edge.get("index", 0)))
    if not entry:
        raise TransformError("template has no trigger to start Run now from")
    wj.add_node(
        wf,
        {
            "id": str(uuid.uuid4()),
            "name": RUN_NODE_NAME,
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": wj.position_near(triggers[0], dy=-200),
            "webhookId": hook.path,
            "parameters": {
                "httpMethod": "POST",
                "path": hook.path,
                "authentication": "headerAuth",
                "responseMode": "onReceived",
                "options": {},
            },
            "credentials": {"httpHeaderAuth": {"id": hook.credential.id, "name": hook.credential.name}},
        },
    )
    for target, input_index in entry:
        wj.connect(wf, RUN_NODE_NAME, target, input_index=input_index)


def _clean_node(n: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in n.items() if k in NODE_KEYS}
    out.setdefault("id", str(uuid.uuid4()))
    return out
