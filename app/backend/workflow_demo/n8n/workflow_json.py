"""Helpers for reading and editing n8n workflow JSON.

n8n stores edges as ``connections[source]["main"][output_index] = [{"node": target, ...}]``.
Credentials are referenced per node as ``node["credentials"][credential_type] = {"id", "name"}``.
Templates in ``catalog/`` use *credential slots* instead of real IDs: the reference id is
``"slot:<name>"`` and is replaced with a real credential at deploy time.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

Workflow = dict[str, Any]
Node = dict[str, Any]

CREDENTIAL_SLOT_PREFIX = "slot:"
TEMPLATE_KEYS = ("name", "nodes", "connections", "settings")
_NODE_ID_NAMESPACE = uuid.UUID("6f1d3c2e-5a0b-4c8e-9a51-2b7c0d4e8f10")


class WorkflowEditError(ValueError):
    """Raised when a workflow doesn't have the shape an edit expects."""


def node(wf: Workflow, name: str) -> Node:
    for n in wf["nodes"]:
        if n["name"] == name:
            return n
    raise WorkflowEditError(f"node {name!r} not found")


def has_node(wf: Workflow, name: str) -> bool:
    return any(n["name"] == name for n in wf["nodes"])


def nodes_of_type(wf: Workflow, node_type: str) -> list[Node]:
    return [n for n in wf["nodes"] if n["type"] == node_type]


def new_node_id(workflow_name: str, node_name: str) -> str:
    """Deterministic node id so regenerated templates don't churn."""
    return str(uuid.uuid5(_NODE_ID_NAMESPACE, f"{workflow_name}/{node_name}"))


def add_node(wf: Workflow, new: Node) -> Node:
    if has_node(wf, new["name"]):
        raise WorkflowEditError(f"node {new['name']!r} already exists")
    wf["nodes"].append(new)
    return new


def remove_node(wf: Workflow, name: str) -> None:
    node(wf, name)  # raises if missing
    wf["nodes"] = [n for n in wf["nodes"] if n["name"] != name]
    connections = wf.setdefault("connections", {})
    connections.pop(name, None)
    for outputs in connections.values():
        for branches in outputs.values():
            for i, branch in enumerate(branches):
                branches[i] = [edge for edge in (branch or []) if edge["node"] != name]


def targets(wf: Workflow, source: str, output: int = 0) -> list[str]:
    branches = wf.get("connections", {}).get(source, {}).get("main", [])
    if output >= len(branches):
        return []
    return [edge["node"] for edge in (branches[output] or [])]


def connect(wf: Workflow, source: str, target: str, *, output: int = 0, input_index: int = 0) -> None:
    node(wf, source)
    node(wf, target)
    branches = wf.setdefault("connections", {}).setdefault(source, {}).setdefault("main", [])
    while len(branches) <= output:
        branches.append([])
    if branches[output] is None:
        branches[output] = []
    if not any(edge["node"] == target for edge in branches[output]):
        branches[output].append({"node": target, "type": "main", "index": input_index})


def edges(wf: Workflow, source: str, target: str) -> list[tuple[int, dict[str, Any]]]:
    """Return ``(output_index, edge)`` for every edge ``source -> target``."""
    branches = wf.get("connections", {}).get(source, {}).get("main", [])
    return [
        (output, edge)
        for output, branch in enumerate(branches)
        for edge in (branch or [])
        if edge["node"] == target
    ]


def disconnect(wf: Workflow, source: str, target: str, *, output: int | None = None) -> None:
    """Remove edges ``source -> target`` (only on ``output`` if given)."""
    branches = wf.get("connections", {}).get(source, {}).get("main", [])
    found = False
    for i, branch in enumerate(branches):
        if output is not None and i != output:
            continue
        kept = [edge for edge in (branch or []) if edge["node"] != target]
        found = found or len(kept) != len(branch or [])
        branches[i] = kept
    if not found:
        raise WorkflowEditError(f"no connection {source!r} -> {target!r}")


def insert_between(
    wf: Workflow,
    source: str,
    target: str,
    new: Node,
    *,
    output: int | None = None,
    new_output: int = 0,
) -> None:
    """Replace the edge ``source -> target`` with ``source -> new -> target``.

    The source output (e.g. an IF node's false branch) and the target input (e.g. a Merge
    node's second input) of the original edge are preserved. ``output`` picks the edge when
    the source connects to the target from more than one output.
    """
    candidates = [(o, e) for o, e in edges(wf, source, target) if output is None or o == output]
    if len(candidates) != 1:
        raise WorkflowEditError(
            f"expected one connection {source!r} -> {target!r}, found {len(candidates)}; pass output="
        )
    source_output, edge = candidates[0]
    disconnect(wf, source, target, output=source_output)
    add_node(wf, new)
    connect(wf, source, new["name"], output=source_output)
    connect(wf, new["name"], target, output=new_output, input_index=edge.get("index", 0))


def set_credential_slot(n: Node, credential_type: str, slot: str) -> None:
    """Point a node at a credential slot, replacing any existing credential references."""
    n["credentials"] = {credential_type: {"id": f"{CREDENTIAL_SLOT_PREFIX}{slot}", "name": slot}}


def credential_slots(wf: Workflow) -> list[tuple[str, str, str]]:
    """Return ``(node_name, credential_type, slot)`` for every slot reference."""
    found = []
    for n in wf["nodes"]:
        for credential_type, ref in (n.get("credentials") or {}).items():
            ref_id = str(ref.get("id", ""))
            if ref_id.startswith(CREDENTIAL_SLOT_PREFIX):
                found.append((n["name"], credential_type, ref_id[len(CREDENTIAL_SLOT_PREFIX) :]))
    return found


def real_credential_refs(wf: Workflow) -> list[tuple[str, str, str]]:
    """Return credential references that are *not* slots (leftovers from the original account)."""
    found = []
    for n in wf["nodes"]:
        for credential_type, ref in (n.get("credentials") or {}).items():
            ref_id = str(ref.get("id", ""))
            if not ref_id.startswith(CREDENTIAL_SLOT_PREFIX):
                found.append((n["name"], credential_type, ref_id))
    return found


def as_template(wf: Workflow, name: str) -> Workflow:
    """Copy only the fields n8n's create-workflow API accepts, with a new name."""
    out = {key: copy.deepcopy(wf[key]) for key in TEMPLATE_KEYS if key in wf}
    out["name"] = name
    out.setdefault("settings", {"executionOrder": "v1"})
    out.setdefault("connections", {})
    return out


def position_near(n: Node, dx: int = 0, dy: int = 0) -> list[int]:
    x, y = n.get("position", [0, 0])
    return [int(x) + dx, int(y) + dy]
