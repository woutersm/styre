"""`styre.server`: finding the model server from styre's pi config, and reading /status.

No network: every read goes through a fake `fetch`. The shapes are modelhost's, captured from
a real `/status` on 2026-09-28.
"""
import json
import urllib.error

import pytest

from styre import config, server

MODELHOST_STATUS = {
    "schema_version": 5, "ready": True, "maximum_context_tokens": 262144,
    "memory_pressure": "normal",
    "admission": {"waiting": 0, "waiting_memory": 0, "waiting_concurrency": 0,
                  "suspended": 0, "draining": False, "oldest_wait_ms": 0},
}


@pytest.fixture(autouse=True)
def pi_dir(tmp_path, monkeypatch):
    d = tmp_path / "pi"
    d.mkdir()
    (d / "settings.json").write_text(json.dumps(
        {"defaultProvider": "modelhost", "defaultModel": "m"}))
    (d / "models.json").write_text(json.dumps({"providers": {"modelhost": {
        "baseUrl": "http://host:8000/v1", "apiKey": "$TEST_MODELHOST_KEY",
        "models": [{"id": "m", "contextWindow": 120000}]}}}))
    monkeypatch.setattr(config, "PI_CONFIG_DIR", d)
    monkeypatch.setenv("TEST_MODELHOST_KEY", "sekret")
    server._cache.update(at=None, value=None)
    return d


def test_provider_comes_from_the_default_and_expands_an_env_key():
    p = server.provider()
    assert p == {"name": "modelhost", "base_url": "http://host:8000/v1", "key": "sekret",
                 "context_window": 120000}


def test_no_default_provider_means_nothing_to_watch(pi_dir):
    (pi_dir / "settings.json").write_text("{}")
    assert server.provider() is None
    assert server.read_status(lambda url, key: pytest.fail("fetched")) is None


def test_status_reads_modelhost_and_calls_the_root_not_v1():
    seen = {}

    def fetch(url, key):
        seen.update(url=url, key=key)
        return MODELHOST_STATUS

    s = server.read_status(fetch)
    assert seen == {"url": "http://host:8000/status", "key": "sekret"}
    assert s == {"server": "modelhost", "ready": True, "memory_pressure": "normal", "waiting": 0,
                 "waiting_memory": 0, "suspended": 0, "oldest_wait_ms": 0,
                 "max_context": 262144}


def test_a_server_without_status_gets_no_line():
    """mlxserve has no /status: a 404 is not a fault to show."""
    def fetch(url, key):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    assert server.read_status(fetch) is None


def test_an_unreachable_server_is_reported():
    def fetch(url, key):
        raise urllib.error.URLError("timed out")

    assert server.read_status(fetch) == {"server": "modelhost", "error": "unreachable (timed out)"}


def test_a_rejected_key_is_reported():
    def fetch(url, key):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    assert server.read_status(fetch)["error"] == "HTTP 401"


def test_status_is_cached_so_the_panel_poll_does_not_hammer_the_host():
    calls = []

    def fetch(url, key):
        calls.append(url)
        return MODELHOST_STATUS

    server.status(fetch, now=100.0)
    server.status(fetch, now=100.0 + server.CACHE_SECONDS - 0.1)
    assert len(calls) == 1
    server.status(fetch, now=100.0 + server.CACHE_SECONDS + 0.1)
    assert len(calls) == 2
