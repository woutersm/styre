"""The model server's own account of itself, for `styre watch`'s live panel.

`styre watch` otherwise reads only files on this machine. This is its one outbound call,
added on 2026-09-28 when the server became modelhost: a phase that has gone quiet can be a
model thinking, a request queued behind memory, or a server that is not serving, and only
the server can say which. It is still read-only — a GET of `/status`, nothing else.

The server is found the way pi finds it: styre's pi config, its default provider's
`baseUrl` and `apiKey` (a `$NAME` key is read from the environment, as pi does). A server
without `/status` (mlxserve) simply gets no line. The answer is kept for `CACHE_SECONDS`, so
the panel's 2-second poll costs the host one small request every few seconds, and a slow
or unreachable host costs the page at most `TIMEOUT_SECONDS`.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from styre import config

CACHE_SECONDS = 5
TIMEOUT_SECONDS = 1.5

_cache = {"at": None, "value": None}


def provider(config_dir=None):
    """The default provider and model from a pi config, or None when it names none."""
    d = config_dir or config.PI_CONFIG_DIR
    try:
        settings = json.loads((d / "settings.json").read_text(encoding="utf-8"))
        providers = json.loads((d / "models.json").read_text(encoding="utf-8"))["providers"]
        name = settings["defaultProvider"]
        entry = providers[name]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    key = entry.get("apiKey") or ""
    if key.startswith("$"):
        key = os.environ.get(key[1:], "")
    model = next((m for m in entry.get("models", []) if m.get("id") == settings.get("defaultModel")),
                 {})
    return {"name": name, "base_url": entry.get("baseUrl") or "", "key": key,
            "context_window": model.get("contextWindow")}


def status(fetch=None, now=None):
    """The server's status, at most CACHE_SECONDS old; None when there is nothing to show."""
    now = time.monotonic() if now is None else now
    if _cache["at"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return _cache["value"]
    value = read_status(fetch or _get)
    _cache.update(at=now, value=value)
    return value


def read_status(fetch):
    p = provider()
    if not p or not p["base_url"]:
        return None
    root = p["base_url"].rstrip("/").removesuffix("/v1")
    try:
        body = fetch(f"{root}/status", p["key"])
    except urllib.error.HTTPError as e:
        # 404: a server with no /status, like mlxserve — nothing to report, not a fault.
        return None if e.code == 404 else {"server": p["name"], "error": f"HTTP {e.code}"}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        reason = getattr(e, "reason", None) or e
        return {"server": p["name"], "error": f"unreachable ({reason})"}
    if not isinstance(body, dict) or "ready" not in body:
        return None
    admission = body.get("admission") or {}
    return {
        "server": p["name"],
        "ready": bool(body.get("ready")),
        "memory_pressure": body.get("memory_pressure"),
        "waiting": admission.get("waiting") or 0,
        "waiting_memory": admission.get("waiting_memory") or 0,
        "suspended": admission.get("suspended") or 0,
        "oldest_wait_ms": admission.get("oldest_wait_ms") or 0,
        "max_context": body.get("maximum_context_tokens"),
    }


def _get(url, key):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                timeout=TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read())
