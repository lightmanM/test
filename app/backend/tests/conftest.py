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


# --------------------------------------------------------------------------- n8n JavaScript

# Runs a Code node's JavaScript, or fills in a parameter's {{ expressions }}, roughly the way n8n
# does: $input is the node's input items, $('Node') another node's output, $json the current item.
N8N_JS_HARNESS = r"""
const { mode, code, items, nodes } = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const wrap = (list) => ({ all: () => list, first: () => list[0], item: list[0] });
const $input = wrap(items);
const $ = (name) => wrap(nodes[name] || []);
const $json = items[0]?.json;
let result;
if (mode === 'code') {
  result = new Function('$input', '$', code)($input, $);
} else {
  const evaluate = (expr) => new Function('$', '$json', `return (${expr});`)($, $json);
  const text = code.replace(/^=/, '');
  const whole = text.match(/^\{\{([\s\S]*)\}\}$/);
  result = whole && !whole[1].includes('}}')
    ? evaluate(whole[1])
    : text.replace(/\{\{([\s\S]+?)\}\}/g, (_, expr) => String(evaluate(expr)));
}
process.stdout.write(JSON.stringify(result ?? null));
"""


@pytest.fixture
def n8n_js():
    """``n8n_js(code, items, nodes, mode="code"|"expression")``; skips if Node isn't installed."""
    import os
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("node is needed in CI (actions/setup-node)")
        pytest.skip("node is not installed")

    def run(code, items=(), nodes=None, mode="code"):
        payload = {"mode": mode, "code": code, "items": list(items), "nodes": nodes or {}}
        done = subprocess.run(
            [node, "-e", N8N_JS_HARNESS],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    return run


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
