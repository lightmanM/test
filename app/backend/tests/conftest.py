import json
from pathlib import Path

import pytest

from workflow_demo.catalog.build import targets


@pytest.fixture
def load_json():
    def _load(path: Path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def originals(load_json):
    """Fix inputs keyed by workflow id (the team's originals, or the compiled Meegle SDK code)."""
    return {t.workflow_id: load_json(t.fix_input) for t in targets()}
