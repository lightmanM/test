#!/usr/bin/env python3
"""Regenerate the demo templates in catalog/ from the team's originals in demo-project/.

Usage (from the repo root):
  python scripts/build_catalog.py                    # write templates
  python scripts/build_catalog.py --check            # exit 1 if a committed template is stale
  python scripts/build_catalog.py --check-compiled F # exit 1 if F (a fresh compile of the Meegle
                                                     # SDK source) differs from the committed one

The Meegle digest source is n8n Workflow-SDK code; compile it with
  node scripts/compile_n8n_sdk.mjs <sdk.js> catalog/meegle-daily-digest/source.compiled.json
(the compiled file is committed so building needs only Python; CI recompiles to catch drift).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "backend"))

from workflow_demo import paths  # noqa: E402
from workflow_demo.catalog.build import render, strip_ids, targets  # noqa: E402


def display(path: Path) -> str:
    try:
        return str(path.relative_to(paths.REPO_ROOT))
    except ValueError:
        return str(path)


def check_compiled(fresh: Path) -> int:
    committed = paths.CATALOG_DIR / "meegle-daily-digest" / "source.compiled.json"
    fresh_data = strip_ids(json.loads(fresh.read_text(encoding="utf-8")))
    committed_data = strip_ids(json.loads(committed.read_text(encoding="utf-8")))
    if fresh_data == committed_data:
        print(f"up to date  {display(committed)}")
        return 0
    print(f"STALE       {display(committed)} (the SDK source changed; recompile, then rebuild)")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if committed templates are stale")
    parser.add_argument("--check-compiled", type=Path, metavar="FRESH_JSON")
    args = parser.parse_args()

    if args.check_compiled:
        return check_compiled(args.check_compiled)

    stale = []
    for target in targets():
        expected = render(target.build())
        current = target.output.read_text(encoding="utf-8") if target.output.exists() else None
        if current == expected:
            print(f"up to date  {display(target.output)}")
        elif args.check:
            stale.append(target.output)
            print(f"STALE       {display(target.output)}")
        else:
            target.output.write_text(expected, encoding="utf-8")
            print(f"wrote       {display(target.output)}")
    if stale:
        print("Run: python scripts/build_catalog.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
