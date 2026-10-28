"""One frontier model call through Claude Code (`claude -p`).

A call runs the frontier command from styre.json with a JSON schema and a tool allowlist,
the prompt on stdin (a long argument breaks on Windows), and a *deadline*: `claude -p`
prints nothing until it ends, so an idle timeout, the rule styre uses for pi, would never
fire and a wedged call would hang the run. The process gets its own process group so the
deadline can take down the whole tree, as pi does (`styre/process.py`).

Every call writes its stdout and stderr to `log_dir/<role>.<n>.json` / `.err`, and one
`model_call` event to the timeline — the one English sentence a failed call leaves is in
that event and on stderr, never a traceback.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from styre import settings
from styre.process import _NEW_GROUP, kill_tree


@dataclass
class ClaudeUsage:
    """The token and cost accounting of one call; a missing field counts 0."""
    tokens_in: int = 0      # input + cache writes + cache reads
    cached_in: int = 0      # cache reads
    cache_write: int = 0    # cache writes
    tokens_out: int = 0
    thinking: int = 0
    cost_usd: float = 0.0
    turns: int = 0


@dataclass
class ClaudeResult:
    output: dict | None = None   # structured_output, or None
    error: str | None = None     # one English sentence, or None
    usage: ClaudeUsage = field(default_factory=ClaudeUsage)
    seconds: float = 0.0


def _num(value) -> int:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def call(role, prompt, schema, tools, *, cwd, timeline, log_dir, timeout=None) -> ClaudeResult:
    """Run one role call and return its ClaudeResult.

    `schema` is a JSON schema object passed as `--json-schema`; `tools` is a list of tool
    names joined for `--tools`, or empty for none. `timeline` receives the `model_call`
    event; `log_dir` receives the raw stdout and stderr. `timeout` is the deadline in
    seconds, defaulting to `frontier.timeout` from styre.json.
    """
    frontier = settings.load()["frontier"]
    if timeout is None:
        timeout = frontier["timeout"]
    command = list(frontier["command"]) + [
        "-p", "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--tools", ",".join(tools),
        "--no-session-persistence", "--permission-mode", "dontAsk",
    ]
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    n = sum(1 for _ in log_dir.glob(f"{role}.*.json")) + 1
    stdout_path, stderr_path = log_dir / f"{role}.{n}.json", log_dir / f"{role}.{n}.err"

    started = time.monotonic()
    stdout = stderr = ""
    error = None
    try:
        p = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding="utf-8",
                             errors="replace", **_NEW_GROUP)
    except OSError as e:
        error = f"The {role} command `{command[0]}` could not be run: {e.strerror or e}."
        p = None
    else:
        try:
            stdout, stderr = p.communicate(input=prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(p)
            try:
                stdout, stderr = p.communicate(timeout=30)
            except (subprocess.TimeoutExpired, OSError):
                pass
            error = f"The {role} call did not finish within its {timeout}s deadline."
    seconds = round(time.monotonic() - started, 1)
    stdout_path.write_text(stdout or "", encoding="utf-8")
    stderr_path.write_text(stderr or "", encoding="utf-8")

    doc = None
    if error is None:
        try:
            doc = json.loads(stdout)
        except ValueError:
            doc = None
        if doc is not None and not isinstance(doc, dict):
            doc = None
        if doc is not None and doc.get("is_error"):
            errors = doc.get("errors") or []
            detail = errors[0] if errors and isinstance(errors[0], str) else \
                doc.get("subtype") or "an unreported error"
            error = f"The {role} call reported an error: {detail}."
        if error is None and (doc is None or p.returncode != 0):
            error = (f"The {role} call printed output that is not JSON."
                     if (doc is None and p.returncode == 0)
                     else f"The {role} call failed with exit code {p.returncode}.")
        if error is None and doc.get("structured_output") is None:
            error = f"The {role} call returned no structured output."

    u = (doc or {}).get("usage")
    if not isinstance(u, dict):
        u = {}
    details = u.get("output_tokens_details")
    if not isinstance(details, dict):
        details = {}
    usage = ClaudeUsage(
        tokens_in=_num(u.get("input_tokens")) + _num(u.get("cache_creation_input_tokens"))
        + _num(u.get("cache_read_input_tokens")),
        cached_in=_num(u.get("cache_read_input_tokens")),
        cache_write=_num(u.get("cache_creation_input_tokens")),
        tokens_out=_num(u.get("output_tokens")),
        thinking=_num(details.get("thinking_tokens")),
        cost_usd=_num((doc or {}).get("total_cost_usd")),
        turns=_num((doc or {}).get("num_turns")),
    )
    model_usage = (doc or {}).get("modelUsage")
    model = next(iter(model_usage)) if isinstance(model_usage, dict) and model_usage else None
    ok = error is None
    timeline.event("model_call", role=role, model=model,
                   tokens_in=usage.tokens_in, cached_in=usage.cached_in,
                   cache_write=usage.cache_write, tokens_out=usage.tokens_out,
                   thinking=usage.thinking, cost_usd=usage.cost_usd, turns=usage.turns,
                   seconds=seconds, ok=ok, error=error)
    if error:
        print(error, file=sys.stderr)
    return ClaudeResult(output=doc.get("structured_output") if doc is not None else None,
                        error=error, usage=usage, seconds=seconds)
