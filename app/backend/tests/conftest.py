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


# --------------------------------------------------------------------------- API fixtures


@pytest.fixture
def make_settings(tmp_path):
    from workflow_demo.config import Settings

    def _make(**overrides):
        values = {
            "demo_passcode": "pass",
            "admin_passcode": "adminpass",
            "session_secret": "test-secret",
            "database_url": f"sqlite:///{tmp_path / 'test.db'}",
            "public_base_url": "http://testserver",
            "cookie_secure": False,
            "DEMO_FAKE_PLATFORMS": True,
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return _make


@pytest.fixture
def services(make_settings):
    from workflow_demo.app import build_services
    from workflow_demo.services.jobs import InlineJobRunner

    svc = build_services(make_settings(), runner_factory=InlineJobRunner)
    svc.db.create_all()
    return svc


@pytest.fixture
def client(services):
    from fastapi.testclient import TestClient

    from workflow_demo.app import create_app

    with TestClient(create_app(services.settings, services)) as test_client:
        yield test_client


@pytest.fixture
def login(client):
    def _login(username="alice", passcode="pass"):
        return client.post("/api/auth/login", json={"username": username, "passcode": passcode})

    return _login
