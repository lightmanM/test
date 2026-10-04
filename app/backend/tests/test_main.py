"""The ``python -m workflow_demo`` server entrypoint (local runs and the AWS container)."""

import pytest

import workflow_demo.__main__ as entry


@pytest.fixture
def started(monkeypatch, make_settings):
    """Run ``main()`` with uvicorn stubbed out; returns the arguments uvicorn was started with."""
    calls = {}
    monkeypatch.setattr(entry, "get_settings", lambda: make_settings())
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **kwargs: calls.update(kwargs))
    return calls


def test_listens_on_localhost_by_default(started, monkeypatch):
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    entry.main()
    assert started["host"] == "127.0.0.1" and started["port"] == 8000


def test_host_and_port_come_from_the_environment(started, monkeypatch):
    # In a container the app must listen on all interfaces so the proxy container can reach it.
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9000")
    entry.main()
    assert started["host"] == "0.0.0.0" and started["port"] == 9000
