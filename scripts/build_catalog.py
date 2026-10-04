#!/usr/bin/env python3
"""Regenerate the demo templates in catalog/ from the team's originals in demo-project/.

Usage (from the repo root):
  python scripts/build_catalog.py          # write templates
  python scripts/build_catalog.py --check  # exit 1 if any committed template is out of date

The Meegle digest source is n8n Workflow-SDK code; compile it first with
  node scripts/compile_n8n_sdk.mjs <sdk.js> catalog/meegle-daily-digest/source.compiled.json
(the compiled file is committed so this script needs only Python).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "backend"))

from workflow_demo import paths  # noqa: E402
from workflow_demo.catalog import fixes  # noqa: E402

Fix = Callable[[dict[str, Any]], dict[str, Any]]

TARGETS: list[tuple[Path, Path, Fix]] = [
    (
        paths.DEMO_PROJECT_DIR / "Host your own uptime monitoring with scheduled triggers.json",
        paths.CATALOG_DIR / "uptime-monitor" / "workflow.json",
        fixes.fix_uptime,
    ),
    (
        paths.CATALOG_DIR / "meegle-daily-digest" / "source.compiled.json",
        paths.CATALOG_DIR / "meegle-daily-digest" / "workflow.json",
        fixes.fix_meegle_digest,
    ),
    (
        paths.DEMO_PROJECT_DIR / "medium-digest-project" / "workflow" / "medium-digest.workflow.json",
        paths.CATALOG_DIR / "medium-digest" / "workflow.json",
        fixes.fix_medium_digest,
    ),
    (
        paths.DEMO_PROJECT_DIR / "GitHub 合并提交 Diff 通知前端.blueprint.json",
        paths.CATALOG_DIR / "github-merge-slack" / "blueprint.json",
        fixes.fix_github_merge_blueprint,
    ),
]


def render(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if committed templates are stale")
    args = parser.parse_args()

    stale = []
    for source, target, fix in TARGETS:
        expected = render(fix(json.loads(source.read_text(encoding="utf-8"))))
        current = target.read_text(encoding="utf-8") if target.exists() else None
        rel = target.relative_to(paths.REPO_ROOT)
        if current == expected:
            print(f"up to date  {rel}")
            continue
        if args.check:
            stale.append(rel)
            print(f"STALE       {rel}")
        else:
            target.write_text(expected, encoding="utf-8")
            print(f"wrote       {rel}")
    if stale:
        print("Run: python scripts/build_catalog.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
