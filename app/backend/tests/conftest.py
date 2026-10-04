import json
from pathlib import Path

import pytest

from workflow_demo import paths


@pytest.fixture
def load_json():
    def _load(path: Path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def originals(load_json):
    demo = paths.DEMO_PROJECT_DIR
    return {
        "uptime": load_json(demo / "Host your own uptime monitoring with scheduled triggers.json"),
        "meegle": load_json(paths.CATALOG_DIR / "meegle-daily-digest" / "source.compiled.json"),
        "medium": load_json(demo / "medium-digest-project" / "workflow" / "medium-digest.workflow.json"),
        "github": load_json(demo / "GitHub 合并提交 Diff 通知前端.blueprint.json"),
    }
