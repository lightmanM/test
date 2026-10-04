"""Single source of truth for which original becomes which catalog template."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workflow_demo import paths
from workflow_demo.catalog import fixes


@dataclass(frozen=True)
class BuildTarget:
    workflow_id: str
    source: Path  # the team's original, as referenced by catalog.yaml `source`
    fix_input: Path  # file the fix reads: the source itself, or its compiled form
    output: Path
    fix: Callable[[dict[str, Any]], dict[str, Any]]

    def build(self) -> dict[str, Any]:
        return self.fix(json.loads(self.fix_input.read_text(encoding="utf-8")))


def targets() -> list[BuildTarget]:
    demo, catalog = paths.DEMO_PROJECT_DIR, paths.CATALOG_DIR
    uptime_src = demo / "Host your own uptime monitoring with scheduled triggers.json"
    medium_src = demo / "medium-digest-project" / "workflow" / "medium-digest.workflow.json"
    github_src = demo / "GitHub 合并提交 Diff 通知前端.blueprint.json"
    return [
        BuildTarget(
            "uptime-monitor",
            uptime_src,
            uptime_src,
            catalog / "uptime-monitor" / "workflow.json",
            fixes.fix_uptime,
        ),
        BuildTarget(
            "meegle-daily-digest",
            demo / "meegle-daily-digest" / "meegle-daily-digest.n8n-cloud-sdk.js",
            catalog / "meegle-daily-digest" / "source.compiled.json",
            catalog / "meegle-daily-digest" / "workflow.json",
            fixes.fix_meegle_digest,
        ),
        BuildTarget(
            "medium-digest",
            medium_src,
            medium_src,
            catalog / "medium-digest" / "workflow.json",
            fixes.fix_medium_digest,
        ),
        BuildTarget(
            "github-merge-slack",
            github_src,
            github_src,
            catalog / "github-merge-slack" / "blueprint.json",
            fixes.fix_github_merge_blueprint,
        ),
    ]


def render(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


RANDOM_ID_KEYS = frozenset({"id", "nodeIds"})


def strip_ids(data: Any) -> Any:
    """Drop node ids (and group references to them): the Workflow SDK randomizes them per compile."""
    if isinstance(data, dict):
        return {k: strip_ids(v) for k, v in data.items() if k not in RANDOM_ID_KEYS}
    if isinstance(data, list):
        return [strip_ids(v) for v in data]
    return data
