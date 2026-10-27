"""`evals/probe.py` against a fake OpenAI-compatible server that streams like Splash."""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))

import probe  # noqa: E402


class FakeServer(BaseHTTPRequestHandler):
    """Streams a role chunk, a keepalive, ten reasoning tokens 10 ms apart and a usage chunk.
    The prompt token count is the content length over 3.3, so it follows the request."""
    prompts = []
    status = True

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/status" or not FakeServer.status:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"memory_actual": {"current_bytes": 20 * 2 ** 30,
                                             "peak_bytes": 22 * 2 ** 30},
                           "metrics": {"draft_acceptance_rate": 0.37},
                           "active_requests": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        content = body["messages"][0]["content"]
        FakeServer.prompts.append((content, self.headers.get("Authorization")))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def send(obj):
            self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode())
            self.wfile.flush()
        send({"model": "m", "choices": [{"delta": {"role": "assistant", "content": ""}}]})
        time.sleep(0.05)                                   # prefill
        self.wfile.write(b": keepalive\n\n")
        n = min(body["max_tokens"], 10)
        for _ in range(n):
            send({"model": "m", "choices": [{"delta": {"reasoning_content": "x"}}]})
            time.sleep(0.01)
        send({"model": "m", "choices": [{"delta": {}, "finish_reason": "length"}],
              "timings": {"predicted_per_second": 99.0}})
        send({"model": "m", "choices": [], "usage": {
            "prompt_tokens": int(len(content) / 3.3), "completion_tokens": n,
            "prompt_tokens_details": {"cached_tokens": 3}},
            "metrics": {"speculation": {"drafted_tokens": 10, "accepted_draft_tokens": 8}}})
        self.wfile.write(b"data: [DONE]\n\n")


@pytest.fixture
def server():
    FakeServer.prompts = []
    FakeServer.status = True
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeServer)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    httpd.shutdown()


def pi_config(tmp_path, base_url, window=2000, setup=None):
    d = tmp_path / "piconfig"
    d.mkdir()
    (d / "settings.json").write_text(json.dumps({"defaultProvider": "p", "defaultModel": "m"}))
    (d / "models.json").write_text(json.dumps({"providers": {"p": {
        "baseUrl": base_url, "apiKey": "k", "api": "openai-completions",
        "models": [{"id": "m", "contextWindow": window}]}}}))
    if setup:
        (d / "setup.json").write_text(json.dumps(setup))
    return d


def test_probe_measures_each_size_and_each_batch(tmp_path, server):
    config = pi_config(tmp_path, server, setup={"name": "fake"})
    result = probe.run_probe(config, contexts=(256, 512, 4096), batch=(1, 2),
                             batch_context=128, gen=10, log=lambda s: None)
    assert result["setup"] == {"name": "fake"}
    assert result["served"] == "m"
    assert result["peak_memory_gb"] is None
    # 4096 + 10 does not fit a 2,000-token window: skipped, not sent
    assert [r["target"] for r in result["single"]] == [256, 512]
    for row in result["single"]:
        assert row["completion_tokens"] == 10
        assert row["uncached"] == row["prompt_tokens"] - 3
        assert row["ttft_ms"] >= 50                          # the fake's prefill sleep
        assert row["tg_tps"] and row["tg_tps"] < 150         # 9 steps over >= 90 ms
        assert row["server"]["speculation"]["accepted_draft_tokens"] == 8
    assert 0 <= result["single"][1]["prompt_tokens"] - 512 < 60   # filler plus the wrapper text
    assert [r["concurrency"] for r in result["batch"]] == [1, 2]
    assert result["batch"][0]["speedup"] == 1.0
    assert result["batch"][1]["speedup"] > 1.0              # the fake serves both at once


def test_every_request_is_unique_and_authorised(tmp_path, server):
    config = pi_config(tmp_path, server)
    probe.run_probe(config, contexts=(128,), batch=(2,), batch_context=128, gen=4,
                    log=lambda s: None)
    contents = [c for c, _ in FakeServer.prompts]
    assert len(contents) == 4                               # warm-up, one size, two at once
    assert len(set(c.split("\n")[0] for c in contents)) == 4
    assert all(c.startswith("[probe ") for c in contents)
    assert {a for _, a in FakeServer.prompts} == {"Bearer k"}


def test_render_has_the_posts_two_tables(tmp_path, server):
    config = pi_config(tmp_path, server, setup={"name": "fake"})
    result = probe.run_probe(config, contexts=(256,), batch=(1,), batch_context=128, gen=10,
                             log=lambda s: None)
    text = probe.render(result)
    assert text.startswith("# Probe: fake")
    assert "| pp256/tg10 " in text
    assert "| 1x " in text and "| 1.0x " in text
    assert "not measured (fill in by hand)" in text


def test_a_non_openai_provider_is_refused(tmp_path):
    d = pi_config(tmp_path, "http://x/v1")
    models = json.loads((d / "models.json").read_text())
    models["providers"]["p"]["api"] = "anthropic-messages"
    (d / "models.json").write_text(json.dumps(models))
    with pytest.raises(SystemExit, match="not an OpenAI-compatible server"):
        probe.endpoint(d)


def test_an_api_key_named_by_dollar_is_read_from_the_environment(tmp_path, monkeypatch):
    d = pi_config(tmp_path, "http://x/v1")
    models = json.loads((d / "models.json").read_text())
    models["providers"]["p"]["apiKey"] = "$PROBE_TEST_KEY"
    (d / "models.json").write_text(json.dumps(models))
    monkeypatch.setenv("PROBE_TEST_KEY", "secret")
    assert probe.endpoint(d)[1] == "secret"


def test_status_gives_memory_and_acceptance(tmp_path, server):
    config = pi_config(tmp_path, server)
    result = probe.run_probe(config, contexts=(128,), batch=(1,), batch_context=128, gen=10,
                             log=lambda s: None)
    assert result["single"][0]["status"]["current_gib"] == 20.0
    assert result["status_after"]["peak_gib_since_start"] == 22.0
    text = probe.render(result)
    assert "server peak since its start: 22.0 GiB" in text
    assert "draft acceptance over everything the server has served: 37%" in text
    assert "| 80% " in text                                  # this request's 8 of 10


def test_no_status_endpoint_leaves_memory_null(tmp_path, server):
    FakeServer.status = False
    config = pi_config(tmp_path, server)
    result = probe.run_probe(config, contexts=(128,), batch=(1,), batch_context=128, gen=10,
                             log=lambda s: None)
    assert result["status_before"] is None and result["single"][0]["status"] is None
    assert "server peak" not in probe.render(result)
