"""Measure a model server the way speed posts do: prefill and decode at fixed prompt sizes, then
the same request 1, 2 and 4 at a time.

    python evals/probe.py [--pi-config DIR] [--contexts 4096,16384,65536] [--batch 1,2,4]
                          [--batch-context 256] [--batch-gen 512] [--gen 128] [--out FILE]

It talks to the default model of a pi config directory (the one `bench.py` would run), over
its OpenAI-compatible `/chat/completions`, streaming. Every request starts with a fresh random
tag, so no prefix cache can serve the prompt; the prompt is real Python source. Timings are the
client's own, so two servers compare on the same terms; a server's own `timings` and
`speculation` blocks, when it sends them, are kept beside them. The `setup.json` of the config
directory, when there is one, is copied in. A server with a Splash-style `/status` also gives
its memory after each test and its draft acceptance; the peak it reports counts from the
server's start, so it is an upper bound. Otherwise `peak_memory_gb` stays null, to be filled
in by hand from the server's own panel.

A bench (`bench.py`) measures the agentic workload, mostly cached; this measures the host's
ceiling. Run it with nothing else on the server.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench import pi_config_dir, read_model, read_setup  # noqa: E402

CHARS_PER_TOKEN = 3.3   # Python source through a Qwen tokenizer, near enough to aim with
REQUEST_TIMEOUT = 900   # seconds of socket silence before a request is given up


def endpoint(config_dir):
    """`(base_url, api_key, model_id)` of the config's default model."""
    model = read_model(config_dir)
    providers = json.loads((config_dir / "models.json").read_text(encoding="utf-8"))["providers"]
    entry = providers.get(model["provider"]) or {}
    if entry.get("api", "openai-completions") != "openai-completions":
        raise SystemExit(f"Provider {model['provider']} is not an OpenAI-compatible server.")
    if not model["base_url"] or not model["id"]:
        raise SystemExit(f"{config_dir} names no default model with a baseUrl.")
    return model["base_url"].rstrip("/"), entry.get("apiKey"), model["id"]


def python_source():
    """The standard library's own Python files, in a fixed order: real code, the same on
    every run of one Python."""
    root = Path(os.__file__).parent
    for path in sorted(root.glob("*.py")):
        try:
            yield path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue


def filler(tokens):
    """About `tokens` tokens of Python source."""
    want = int(tokens * CHARS_PER_TOKEN)
    parts, have = [], 0
    for text in python_source():
        parts.append(text)
        have += len(text)
        if have >= want:
            break
    return "".join(parts)[:want]


def prompt(tokens):
    """One request's messages: a unique tag first, so no cached prefix matches."""
    code = filler(tokens)
    return [{"role": "user",
             "content": f"[probe {uuid.uuid4()}]\nHere is some Python code:\n```python\n{code}\n"
                        "```\nExplain in detail what this code does."}]


def stream(base_url, api_key, model, messages, gen):
    """Send one streaming request; return its measurements.

    `ttft` is the first chunk carrying text or reasoning, `end` the stream's end, both from
    the moment of sending."""
    body = json.dumps({"model": model, "messages": messages, "max_tokens": gen,
                       "stream": True, "stream_options": {"include_usage": True}}).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{base_url}/chat/completions", data=body, headers=headers)
    sent = time.monotonic()
    first = None
    usage, server, served = {}, {}, None
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue                     # keepalive comments, blank separators
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            served = served or chunk.get("model")
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                if first is None and any(delta.get(k) for k in
                                         ("content", "reasoning_content", "reasoning")):
                    first = time.monotonic()
            if chunk.get("usage"):
                usage = chunk["usage"]
            for key in ("timings", "speculation"):
                if chunk.get(key):
                    server[key] = chunk[key]
            if (chunk.get("metrics") or {}).get("speculation"):
                server["speculation"] = chunk["metrics"]["speculation"]
    end = time.monotonic()
    first = first or end
    prompt_tokens = usage.get("prompt_tokens") or 0
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    return {"prompt_tokens": prompt_tokens, "cached_tokens": cached,
            "completion_tokens": usage.get("completion_tokens") or 0,
            "sent": sent, "first": first, "end": end, "served": served, "server": server}


def server_status(base_url, api_key):
    """Memory and speculation from the server's `/status`, or None when it has none.

    Splash reports `memory_actual` (current and peak since the server started) and
    `metrics.draft_acceptance_rate` (since start, every request ever served)."""
    root = base_url[:-3] if base_url.endswith("/v1") else base_url
    req = urllib.request.Request(f"{root}/status",
                                 headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = json.loads(resp.read())
    except (OSError, ValueError):
        return None
    mem = status.get("memory_actual") if isinstance(status, dict) else None
    if not isinstance(mem, dict):
        return None
    gib = 2 ** 30

    def size(key):
        return round(mem[key] / gib, 1) if isinstance(mem.get(key), (int, float)) else None
    return {"current_gib": size("current_bytes"), "peak_gib_since_start": size("peak_bytes"),
            "draft_acceptance_since_start": (status.get("metrics") or {}).get(
                "draft_acceptance_rate"),
            "active_requests": len(status.get("active_requests") or [])}


def single_row(target, m):
    """One request's numbers, as the post's table has them."""
    uncached = m["prompt_tokens"] - m["cached_tokens"]
    ttft, decode = m["first"] - m["sent"], m["end"] - m["first"]
    steps = max(m["completion_tokens"] - 1, 0)
    return {"target": target, "prompt_tokens": m["prompt_tokens"], "uncached": uncached,
            "completion_tokens": m["completion_tokens"],
            "ttft_ms": round(ttft * 1000, 1),
            "tpot_ms": round(decode / steps * 1000, 1) if steps else None,
            "pp_tps": round(uncached / ttft, 1) if ttft > 0 else None,
            "tg_tps": round(steps / decode, 1) if decode > 0 and steps else None,
            "e2e_s": round(m["end"] - m["sent"], 2), "server": m["server"]}


def batch_row(k, ms, single_tg):
    """`k` requests sent together: total decode throughput over the shared decode window."""
    start = min(m["sent"] for m in ms)
    decode_window = max(m["end"] for m in ms) - min(m["first"] for m in ms)
    prefill_window = max(m["first"] for m in ms) - start
    steps = sum(max(m["completion_tokens"] - 1, 0) for m in ms)
    uncached = sum(m["prompt_tokens"] - m["cached_tokens"] for m in ms)
    tg = steps / decode_window if decode_window > 0 else None
    return {"concurrency": k,
            "tg_tps": round(tg, 1) if tg else None,
            "pp_tps": round(uncached / prefill_window, 1) if prefill_window > 0 else None,
            "speedup": round(tg / single_tg, 2) if tg and single_tg else None,
            "e2e_s": round(max(m["end"] for m in ms) - start, 2)}


def concurrent(k, send):
    """Run `send()` on `k` threads at once; return the measurements in thread order."""
    out, errors = [None] * k, []

    def work(i):
        try:
            out[i] = send()
        except Exception as e:  # recorded, never silently averaged in
            errors.append(e)
    threads = [threading.Thread(target=work, args=(i,)) for i in range(k)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise errors[0]
    return out


def run_probe(config_dir, contexts=(4096, 16384, 65536), batch=(1, 2, 4), batch_context=256,
              gen=128, log=print, batch_gen=None):
    """Measure the config's default model; return the result dict."""
    config_dir = Path(config_dir)
    base_url, api_key, model = endpoint(config_dir)
    window = read_model(config_dir)["context_window"]
    result = {"setup": read_setup(config_dir), "model": read_model(config_dir), "served": None,
              "started": datetime.now().astimezone().isoformat(), "gen": gen,
              "single": [], "batch": [], "peak_memory_gb": None,
              "status_before": server_status(base_url, api_key), "status_after": None}
    log(f"probe {model} at {base_url}")
    busy = (result["status_before"] or {}).get("active_requests")
    if busy:
        log(f"warning: the server has {busy} request(s) in flight; the numbers will be low")
    stream(base_url, api_key, model, prompt(64), 8)        # warm-up, not recorded
    for target in contexts:
        if window and target + gen > window:
            log(f"pp{target}: skipped, over the {window:,}-token context window")
            continue
        m = stream(base_url, api_key, model, prompt(target), gen)
        result["served"] = result["served"] or m["served"]
        row = single_row(target, m)
        row["status"] = server_status(base_url, api_key)
        result["single"].append(row)
        log(f"pp{target}: ttft {row['ttft_ms']} ms, pp {row['pp_tps']} t/s, tg {row['tg_tps']} t/s")
    # The batch test is about decode: a long prefill runs one request at a time on most hosts
    # and would hide whether decoding batches. So a short prompt and a longer generation.
    batch_gen = batch_gen or gen
    single_tg = None
    for k in batch:
        ms = concurrent(k, lambda: stream(base_url, api_key, model, prompt(batch_context),
                                          batch_gen))
        if k == 1:
            single_tg = single_row(batch_context, ms[0])["tg_tps"]
        row = batch_row(k, ms, single_tg)
        result["batch"].append(row)
        log(f"{k}x: tg {row['tg_tps']} t/s, speedup {row['speedup']}")
    result["status_after"] = server_status(base_url, api_key)
    return result


def render(result):
    """The result as two markdown tables, the post's shape."""
    from styre.summarize import table

    def cell(v):
        return "-" if v is None else f"{v:,}" if isinstance(v, int) else str(v)
    setup = result.get("setup") or {}
    m = result.get("model") or {}
    name = setup.get("name") or f"{m.get('provider')}/{m.get('id')}"
    lines = [f"# Probe: {name}", "",
             f"started {result['started']}, {result['gen']} tokens per request", ""]
    def accepted(r):
        spec = (r.get("server") or {}).get("speculation") or {}
        drafted, ok = spec.get("drafted_tokens"), spec.get("accepted_draft_tokens")
        return f"{ok / drafted:.0%}" if drafted and ok is not None else "-"

    def memory(r):
        return cell((r.get("status") or {}).get("current_gib"))
    lines += [table(["Test", "Prompt", "TTFT ms", "TPOT ms", "pp t/s", "tg t/s", "E2E s",
                     "Draft accepted", "Mem GiB"],
                    [[f"pp{r['target']}/tg{result['gen']}", cell(r["prompt_tokens"]),
                      cell(r["ttft_ms"]), cell(r["tpot_ms"]), cell(r["pp_tps"]),
                      cell(r["tg_tps"]), cell(r["e2e_s"]), accepted(r), memory(r)]
                     for r in result["single"]]), ""]
    lines += [table(["Batch", "tg t/s", "pp t/s", "Speedup", "E2E s"],
                    [[f"{r['concurrency']}x", cell(r["tg_tps"]), cell(r["pp_tps"]),
                      "-" if r["speedup"] is None else f"{r['speedup']}x", cell(r["e2e_s"])]
                     for r in result["batch"]]), ""]
    after = result.get("status_after") or {}
    if after.get("peak_gib_since_start") is not None:
        lines.append(f"server peak since its start: {after['peak_gib_since_start']} GiB "
                     "(an upper bound for this probe)")
    if after.get("draft_acceptance_since_start") is not None:
        lines.append(f"draft acceptance over everything the server has served: "
                     f"{after['draft_acceptance_since_start']:.0%}")
    lines.append(f"peak memory: {result.get('peak_memory_gb') or 'not measured (fill in by hand)'}")
    return "\n".join(lines) + "\n"


def ints(text):
    return tuple(int(x) for x in text.split(",") if x.strip())


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(prog="probe", description=__doc__.strip().splitlines()[0])
    ap.add_argument("--pi-config", default=None, help="the pi config directory (default: styre's)")
    ap.add_argument("--contexts", default="4096,16384,65536", help="prompt sizes, in tokens")
    ap.add_argument("--batch", default="1,2,4", help="concurrency levels")
    ap.add_argument("--batch-context", type=int, default=256, help="prompt size for the batch test")
    ap.add_argument("--batch-gen", type=int, default=512, help="tokens generated in the batch test")
    ap.add_argument("--gen", type=int, default=128, help="tokens generated per request")
    ap.add_argument("--out", default=None, help="write the result JSON here")
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    result = run_probe(pi_config_dir(args.pi_config), ints(args.contexts), ints(args.batch),
                       args.batch_context, args.gen, log=lambda s: print(s, file=sys.stderr),
                       batch_gen=args.batch_gen)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(render(result), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
