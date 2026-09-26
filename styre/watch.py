"""`styre watch`: a local, read-only web view of the runs in this repository.

It answers a question no other verb does — *is the phase running right now going to make
it* — and it answers it from the same files `summarize` reads, with the same rule: nothing
here is taken from the agent's account of its own work.

Read-only, and bound to localhost. It never writes into `.styre/`, never touches git, and
has no route that changes anything: a monitor that can break the run it is watching is
worse than no monitor.

Three shapes of read, because they have three different costs:

- **The run list** reads `timeline.jsonl` and nothing else — 4 KB a run, so the index is
  instant no matter how much history is on disk. It is enough to pick a run: phases, gate
  verdicts, commits, and how it ended.
- **A run page** scans that run's `logs/phaseN.events.jsonl` on demand. That is 3-9 MB a
  phase (app held 96 MB across three runs on 2026-09-25), so it costs seconds, once.
- **The live panel** never rescans. `_Tail` keeps a byte offset per phase and reads only
  what was appended since the last poll, which is what makes a 2-second refresh free
  against a 9 MB file that is still growing.

The danger line on a sparkline is calibrated from this repo's own history — the lowest peak
context at which a phase here has ever stopped — rather than from a constant. A number
measured on one model host is not a fact about the next one.
"""
from __future__ import annotations

import html
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from styre.config import DEFAULT_TIMEOUT
from styre.rundir import RUNS, RunDir
from styre.summarize import (
    Run,
    collect,
    parse_ts,
    read_jsonl,
    read_timeline,
    where_to_look,
)

DEFAULT_PORT = 8765
POLL_SECONDS = 2
TAIL_BYTES = 4096          # enough of phaseN.log for the live panel: ~40 rendered lines
STALE_SECONDS = 300        # no output for this long is worth saying out loud; the idle
                           # watchdog only fires at --timeout, hours later


# --------------------------------------------------------------------------- reading


def runs():
    """Every run directory, newest first by id (which is a timestamp)."""
    if not RUNS.is_dir():
        return []
    return [RunDir(d) for d in sorted(RUNS.glob("*"), key=lambda d: d.name, reverse=True)
            if d.is_dir()]


def find_run(run_id):
    """The run with this id, or None. Only a plain directory name is accepted — a path, or
    anything with a separator in it, is refused rather than resolved."""
    if not run_id or "/" in run_id or "\\" in run_id or run_id in (".", ".."):
        return None
    root = RUNS / run_id
    return RunDir(root) if root.is_dir() else None


def timeline_only(run):
    """A Run built from `timeline.jsonl` alone: the index's reader, and the cheap half of
    everything else. No event file is opened, so this costs the same on a 12-phase run as
    on a one-phase one."""
    summary = Run(id=run.id)
    read_timeline(run, summary)
    return summary


def live_step(run):
    """(phase, step, started_ts) for the pi process that has started and not ended, or None.

    Read off the timeline rather than by looking for a process: styre writes `pi_start`
    before it spawns and `pi_end` in a finally, so the pair is the honest record of what is
    in flight — including after a kill, where the absence of `pi_end` is itself the fact.
    """
    open_step = None
    for e in read_jsonl(run.timeline):
        kind = e.get("event")
        if kind == "pi_start":
            open_step = (e.get("phase"), e.get("step"), e.get("ts"))
        elif kind in ("pi_end", "run_end"):
            open_step = None
    return open_step


def unclosed(summary):
    """True when an invocation never reached `run_end`.

    Not the same as running, and conflating the two was this module's first bug: app's
    `20260921-045131` holds **17 `run_start`s against 5 `run_end`s** — twelve invocations
    killed at the terminal — so every dead run in the list read as live. A missing
    `run_end` says nobody wrote the ending, which a kill and a run in progress produce
    identically. Freshness is what separates them.
    """
    return len(summary.starts) > len(summary.ends)


def freshness(run):
    """Seconds since anything in this run directory was last written, or None if empty.

    The timeline and the phase logs together, because between phases the timeline moves
    while no events file does.
    """
    stamps = [s for s in (mtime(p) for p in [run.timeline, *run.root.glob("logs/*")])
              if s is not None]
    return (time.time() - max(stamps)) if stamps else None


def run_state(run, summary):
    """(label, css class, is_live) for one run.

    A run silent for longer than the orchestrator's own idle limit cannot be in progress:
    `run` would have killed the pi process and written its ending. So that bound is
    `DEFAULT_TIMEOUT`, styre's own number, rather than a threshold invented here.

    Between the two is deliberately *not* called dead. pi prints nothing at all between
    `tool_execution_start` and `tool_execution_end`, so a phase inside a long test suite is
    indistinguishable from a stalled one from out here — the page reports how long it has
    been quiet and leaves the judgement to the reader.
    """
    if not unclosed(summary):
        last = summary.last
        return f"exit {last.get('exit_code')}" if last else "no run_end", "dim", False
    quiet = freshness(run)
    if quiet is None:
        return "nothing written", "dim", False
    if quiet > DEFAULT_TIMEOUT:
        return f"abandoned, no run_end ({fmt_seconds(quiet)} quiet)", "bad", False
    if quiet > STALE_SECONDS:
        return f"running, silent {fmt_seconds(quiet)}", "warn", True
    return "running", "ok", True


def mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def staleness(run, n):
    """Seconds since anything was appended to phase n's event file, or None if there is
    none. This is the "is it alive" number: a phase working and printing is never stale."""
    stamp = mtime(run.events(n))
    return None if stamp is None else max(0.0, time.time() - stamp)


class _Tail:
    """Per-phase incremental reader for one events file.

    Keeps the byte offset it has read to, plus the usage points it has seen, so a poll costs
    only the bytes appended since the last one. A file that shrank was replaced (a new run
    in the same directory), so the state is dropped and read again from the start.
    """

    def __init__(self):
        self.offset = 0
        self.points = []        # (arrival datetime, totalTokens)
        self.tool_errors = {}
        self.decode_tokens = 0      # output tokens, over messages we could time
        self.decode_seconds = 0.0   # message_start -> message_end, summed
        self._message_start = None

    def update(self, path):
        size = path.stat().st_size if path.exists() else 0
        if size < self.offset:
            self.__init__()
        if size == self.offset:
            return self
        with open(path, "rb") as f:
            f.seek(self.offset)
            blob = f.read()
        # A half-written last line is normal against a file being appended to. Keep the
        # offset at the last newline so the tail of the line is read next time, whole.
        cut = blob.rfind(b"\n") + 1
        self.offset += cut
        for line in blob[:cut].decode("utf-8", "replace").splitlines():
            self._add(line)
        return self

    def _add(self, line):
        try:
            wrapper = json.loads(line)
            event = json.loads(wrapper["line"])
        except (json.JSONDecodeError, KeyError, TypeError):
            return
        if not isinstance(event, dict):
            return
        stamp = parse_ts(wrapper.get("ts"))
        if event.get("type") == "message_start":
            self._message_start = stamp
        elif event.get("type") == "tool_execution_end" and event.get("isError"):
            name = event.get("toolName") or "?"
            self.tool_errors[name] = self.tool_errors.get(name, 0) + 1
        elif event.get("type") == "message_end":
            usage = (event.get("message") or {}).get("usage")
            total = usage.get("totalTokens") if isinstance(usage, dict) else None
            if total:
                # The x axis is our own arrival stamp, the one the orchestrator writes as
                # each line comes in. pi stamps almost nothing itself, and no duration in
                # this module is read off pi's stream.
                self.points.append((stamp, total))
            output = usage.get("output") if isinstance(usage, dict) else None
            if output and self._message_start and stamp:
                self.decode_seconds += (stamp - self._message_start).total_seconds()
                self.decode_tokens += output
            self._message_start = None

    @property
    def peak(self):
        return max((y for _, y in self.points), default=None)

    @property
    def tokens_per_second(self):
        """Output tokens per second of *model* time: summed over each message's own
        `message_start` -> `message_end` span, so tool execution and the gaps between
        messages are excluded.

        Measured this way it agrees with what the model host reports for itself — 8.58
        against the server log's 8.4-8.9 on app's phase 5, 2026-09-25 — because the span
        covers prefill and decode together, which is also how the server computes its own
        figure.

        The obvious alternative, output over the phase's wall clock, is not the same number
        and is not usable: it reads 0.60 tok/s on a phase whose events file spans a failed
        attempt, a six-hour gap, and the resume that succeeded.
        """
        return self.decode_tokens / self.decode_seconds if self.decode_seconds else None


_TAILS = {}


def tail_for(run, n):
    """The `_Tail` for one phase of one run, created on first use and kept for the life of
    the server process. This is what makes a repeat visit to a run page cheap."""
    key = (run.id, n)
    if key not in _TAILS:
        _TAILS[key] = _Tail()
    return _TAILS[key].update(run.events(n))


def log_tail(run, n, limit=TAIL_BYTES):
    """The last few KB of phase n's readable log, whole lines only."""
    path = run.log(n)
    if not path.exists():
        return ""
    with open(path, "rb") as f:
        size = f.seek(0, 2)
        f.seek(max(0, size - limit))
        blob = f.read()
    text = blob.decode("utf-8", "replace")
    return text if size <= limit else text.split("\n", 1)[-1]


def danger_line(summaries):
    """The lowest peak context at which a phase in this repo has ever stopped, or None.

    Self-calibrating on purpose. The absolute numbers belong to one model host — 85k is
    where phases got slowest on app's, and 130,901 is where one was refused outright — and
    hardcoding either would make the warning wrong on the next machine. A repo where
    nothing has died yet gets no line, which is the honest answer.

    A phase that stopped and was later resumed reads as committed here, and its peak is the
    high-water mark of every attempt it took. That is the number worth seeing anyway.
    """
    peaks = [p.usage.peak for s in summaries for p in s.phases
             if p.usage.peak and p.status and p.status != "committed"]
    return min(peaks) if peaks else None


# --------------------------------------------------------------------------- rendering


def sparkline(points, threshold=None, width=220, height=40):
    """Context over time as an inline SVG. No library, no CDN, no request off this machine.

    `points` is [(x, y)] already in plot order; x is seconds since the phase's first
    measured message. A single point is drawn as a dot — a one-message phase has no slope,
    and pretending otherwise by drawing a flat line reads as "steady" when it means "one
    sample".
    """
    ys = [y for _, y in points]
    if not ys:
        return '<span class="dim">no context measured yet</span>'
    top = max(max(ys), threshold or 0) * 1.08 or 1
    xs = [x for x, _ in points]
    span = (max(xs) - min(xs)) or 1
    pad = 2

    def place(x, y):
        return (pad + (x - min(xs)) / span * (width - 2 * pad),
                height - pad - (y / top) * (height - 2 * pad))

    parts = [f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" '
             f'height="{height}" role="img">']
    if threshold:
        _, ty = place(min(xs), threshold)
        parts.append(f'<line x1="0" y1="{ty:.1f}" x2="{width}" y2="{ty:.1f}" '
                     f'class="danger" />')
    if len(points) == 1:
        cx, cy = place(*points[0])
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.5" class="dot" />')
    else:
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in (place(x, y) for x, y in points))
        parts.append(f'<polyline points="{path}" class="line" />')
    parts.append("</svg>")
    return "".join(parts)


def series(run, n):
    """Phase n's context over time, as seconds-since-first-sample against totalTokens."""
    points = [(t, y) for t, y in tail_for(run, n).points if t is not None]
    if not points:
        return []
    start = points[0][0]
    return [((t - start).total_seconds(), y) for t, y in points]


def rate(run, n):
    """Tokens of context per minute over phase n so far, or None with too little to say."""
    points = series(run, n)
    if len(points) < 2 or points[-1][0] <= 0:
        return None
    return (points[-1][1] - points[0][1]) / (points[-1][0] / 60)


def esc(text):
    return html.escape("" if text is None else str(text))


def fmt_seconds(value):
    """Seconds at the scale a reader wants them: a phase runs for minutes, a run abandoned
    on Monday has been quiet for days, and `2512m 49s` is neither."""
    if value is None:
        return "-"
    value = int(value)
    if value < 60:
        return f"{value}s"
    if value < 3600:
        return f"{value // 60}m {value % 60:02d}s"
    if value < 86400:
        return f"{value // 3600}h {value % 3600 // 60:02d}m"
    return f"{value // 86400}d {value % 86400 // 3600:02d}h"


def fmt_count(value):
    return "-" if value is None else f"{value:,}"


def fmt_rate(value):
    return "-" if value is None else f"{value:.1f}"


CSS = """
:root { --bg:#fbfaf8; --fg:#1d1d1f; --dim:#6b6b70; --rule:#e2e0db; --card:#fff;
        --ok:#1a7f37; --bad:#b3261e; --warn:#8a6100; --line:#3b6ea5; --danger:#b3261e; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16161a; --fg:#ececed; --dim:#9b9ba1; --rule:#2c2c33; --card:#1d1d22;
          --ok:#4ac26b; --bad:#ff7b72; --warn:#d9a441; --line:#7aa7d6; --danger:#ff7b72; }
}
* { box-sizing:border-box; }
body { margin:0; padding:24px 16px 48px; background:var(--bg); color:var(--fg);
       font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
.wrap { max-width:1000px; margin:0 auto; }
h1 { font-size:20px; margin:0 0 4px; }
h2 { font-size:15px; margin:28px 0 8px; }
a { color:inherit; }
.dim { color:var(--dim); }
.facts { color:var(--dim); margin:0 0 18px; }
table { border-collapse:collapse; width:100%; }
th,td { text-align:left; padding:6px 10px 6px 0; border-bottom:1px solid var(--rule);
        vertical-align:middle; white-space:nowrap; }
th { font-weight:600; color:var(--dim); font-size:12px; text-transform:uppercase;
     letter-spacing:.04em; }
td.n, th.n { text-align:right; font-variant-numeric:tabular-nums; }
.wide { white-space:normal; }
.ok { color:var(--ok); } .bad { color:var(--bad); } .warn { color:var(--warn); }
.card { background:var(--card); border:1px solid var(--rule); border-radius:8px;
        padding:14px 16px; margin:12px 0; }
.big { font-size:26px; font-variant-numeric:tabular-nums; }
.grid { display:flex; flex-wrap:wrap; gap:24px; align-items:flex-end; }
.spark { display:block; }
.spark .line { fill:none; stroke:var(--line); stroke-width:1.6; }
.spark .dot { fill:var(--line); }
.spark .danger { stroke:var(--danger); stroke-width:1; stroke-dasharray:3 3; opacity:.8; }
pre { background:var(--card); border:1px solid var(--rule); border-radius:8px;
      padding:12px; overflow-x:auto; font-size:12px; line-height:1.45; margin:8px 0; }
.scroll { overflow-x:auto; }
"""


def page(title, body):
    return (f"<!doctype html><html><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title><style>{CSS}</style></head>"
            f"<body><div class=wrap>{body}</div></body></html>")


def status_class(status):
    if status == "committed":
        return "ok"
    return "bad" if status else "dim"


def index_html():
    """The run list, from timelines only."""
    rows = []
    for run in runs():
        s = timeline_only(run)
        first = s.first
        committed = sum(1 for p in s.phases if p.status == "committed")
        state, state_class, live = run_state(run, s)
        step = live_step(run) if live else None
        note = ""
        if step and step[0]:
            stale = staleness(run, step[0])
            note = f"phase {step[0]} {esc(step[1] or '')}"
            if stale is not None and stale > STALE_SECONDS:
                note += f' <span class="bad">silent {fmt_seconds(stale)}</span>'
        rows.append(
            f"<tr><td><a href='/run/{esc(run.id)}'>{esc(run.id)}</a></td>"
            f"<td>{esc(first.get('design') or '-')}</td>"
            f"<td>{esc(first.get('branch') or '-')}</td>"
            f"<td class=n>{len(s.phases)}</td>"
            f"<td class=n>{committed}</td>"
            f"<td class='{state_class}'>{esc(state)}</td>"
            f"<td class=wide>{note}</td></tr>")
    if not rows:
        body = "<h1>styre watch</h1><p class=facts>No runs under <code>.styre/runs/</code>.</p>"
        return page("styre watch", body)
    table = ("<table><tr><th>Run</th><th>Design</th><th>Branch</th><th class=n>Phases</th>"
             "<th class=n>Committed</th><th>State</th><th>Now</th></tr>"
             + "".join(rows) + "</table>")
    return page("styre watch",
                f"<h1>styre watch</h1><p class=facts>{len(rows)} run(s) in this repository. "
                f"This list reads only each run's timeline, so it stays instant.</p>"
                f"<div class=scroll>{table}</div>")


def phase_rows(run, summary, threshold):
    rows = []
    for p in summary.phases:
        rows.append(
            f"<tr><td class=n>{p.n}</td><td class=wide>{esc(p.name)}</td>"
            f"<td class='{status_class(p.status)}'>{esc(p.status or '?')}</td>"
            f"<td><code>{esc((p.sha or '-')[:7])}</code></td>"
            f"<td class=n>{p.agent_seconds / 60:.0f}m</td>"
            f"<td class=n>{p.rounds if p.rounds is not None else '-'}</td>"
            f"<td class=n>{p.self_rounds if p.self_rounds is not None else '-'}</td>"
            f"<td class=n>{fmt_count(p.usage.peak)}</td>"
            f"<td class=n>{fmt_rate(tail_for(run, p.n).tokens_per_second)}</td>"
            f"<td>{sparkline(series(run, p.n), threshold, width=150, height=30)}</td></tr>")
    return "".join(rows)


def run_html(run):
    """One run, scanned on demand. The live panel below refreshes itself."""
    summary = collect(run)
    threshold = danger_line([timeline_only(r) if r.id != run.id else summary
                             for r in runs()])
    first, last = summary.first, summary.last
    facts = [f"design <code>{esc(first.get('design'))}</code>" if first.get("design") else None,
             f"branch <code>{esc(first.get('branch'))}</code>" if first.get("branch") else None,
             f"pi {esc(first.get('pi_version'))}" if first.get("pi_version") else None,
             f"styre {esc(first.get('styre'))}" if first.get("styre") else None]
    head = [f"<h1><a href='/' class=dim>runs</a> / {esc(run.id)}</h1>",
            "<p class=facts>" + ", ".join(f for f in facts if f) + "</p>"]
    if len(summary.starts) > 1:
        head.append(f"<p class=facts>{len(summary.starts)} invocations — a resumed run "
                    f"appends to the timeline it continues, so a phase's peak context is "
                    f"the high-water mark of every attempt it took.</p>")
    if last.get("stopped"):
        head.append(f"<div class=card><b class=bad>Stopped.</b> {esc(last['stopped'])}</div>")

    state, state_class, is_live = run_state(run, summary)
    live = ("<div class=card id=live>waiting…</div>" if is_live else
            f"<p class='{state_class}'>{esc(state)}</p>"
            "<p class=dim>Nothing is polling.</p>")
    script = (f"<script>async function tick(){{"
              f"try{{const r=await fetch('/api/live/{run.id}');"
              f"document.getElementById('live').innerHTML=(await r.json()).html;}}"
              f"catch(e){{}} setTimeout(tick,{POLL_SECONDS * 1000});}}"
              f"if(document.getElementById('live'))tick();</script>")

    rate_note = ("<p class=dim>tok/s is output tokens per second of model time — each "
                 "message's own start-to-end span, so tool calls and the waits between "
                 "messages are left out. It falls as peak context rises.</p>")
    note = (f"<p class=dim>The dashed line is {threshold:,} tokens — the lowest peak context "
            f"at which a phase in this repository has stopped.</p>" if threshold else
            "<p class=dim>No phase in this repository has stopped yet, so the sparklines "
            "carry no danger line.</p>")
    table = ("<div class=scroll><table><tr><th class=n>#</th><th>Phase</th><th>Status</th>"
             "<th>Commit</th><th class=n>Agent</th><th class=n>Fix</th><th class=n>Self</th>"
             "<th class=n>Peak ctx</th><th class=n>tok/s</th>"
             "<th>Context over time</th></tr>"
             + phase_rows(run, summary, threshold) + "</table></div>")
    look = "\n".join(where_to_look(summary)).strip()
    return page(f"{run.id} — styre watch",
                "".join(head) + f"<h2>Now</h2>{live}{script}"
                + f"<h2>Phases</h2>{table}{rate_note}{note}"
                + f"<h2>Where to look</h2><pre>{esc(look)}</pre>")


def live_html(run):
    """The polled panel: what is happening in the phase that is running."""
    summary = timeline_only(run)
    state, state_class, is_live = run_state(run, summary)
    if not is_live:
        return (f"<b class='{state_class}'>{esc(state)}</b> "
                f"<span class=dim>Reload for the final table.</span>")
    step = live_step(run)
    if not step or not step[0]:
        return "<b>Between phases.</b> <span class=dim>No pi process is open.</span>"
    n, name, started = step
    tail = tail_for(run, n)
    stale = staleness(run, n)
    began = parse_ts(started)
    elapsed = (time.time() - began.timestamp()) if began else None
    threshold = danger_line([timeline_only(r) for r in runs()])
    per_min = rate(run, n)
    stale_class = "bad" if stale is not None and stale > STALE_SECONDS else "dim"
    cells = [("phase", f"{n} <span class=dim>{esc(name or '')}</span>"),
             ("running", fmt_seconds(elapsed)),
             ("peak ctx", fmt_count(tail.peak)),
             ("ctx/min", "-" if per_min is None else f"{per_min:,.0f}"),
             ("tok/s", fmt_rate(tail.tokens_per_second)),
             ("last output", f"<span class={stale_class}>{fmt_seconds(stale)} ago</span>")]
    grid = "".join(f"<div><div class=dim>{k}</div><div class=big>{v}</div></div>"
                   for k, v in cells)
    errors = ("<div class=dim>" + ", ".join(f"{v} failed {k} call(s)"
                                            for k, v in sorted(tail.tool_errors.items()))
              + "</div>") if tail.tool_errors else ""
    return (f"<div class=grid>{grid}<div>{sparkline(series(run, n), threshold)}</div></div>"
            f"{errors}<pre>{esc(log_tail(run, n))}</pre>")


# --------------------------------------------------------------------------- serving


class Handler(BaseHTTPRequestHandler):
    server_version = "styre-watch"

    def do_GET(self):     # noqa: N802 - the name is BaseHTTPRequestHandler's
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/":
            return self._send(index_html())
        if path.startswith("/run/"):
            run = find_run(path[len("/run/"):])
            return self._send(run_html(run)) if run else self._send_404()
        if path.startswith("/api/live/"):
            run = find_run(path[len("/api/live/"):])
            if not run:
                return self._send_404()
            return self._send(json.dumps({"html": live_html(run)}), "application/json")
        return self._send_404()

    def _send(self, text, kind="text/html; charset=utf-8", status=200):
        blob = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(blob)

    def _send_404(self):
        self._send(page("not found", "<h1>Not found</h1><p><a href='/'>runs</a></p>"),
                   status=404)

    def log_message(self, *args):
        pass          # one line per poll, every two seconds, is noise and nothing else


def serve(port=DEFAULT_PORT, handler=Handler):
    """Serve on localhost until interrupted. Bound to 127.0.0.1 deliberately: the pages
    carry phase prompts, diffs and decisions, and nothing here needs to leave the machine."""
    if not Path(".git").exists():
        print("[styre] warning: no .git here — watch reads .styre/runs/ in the current "
              "directory, so run it from inside the target repository.")
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"[styre] watching {RUNS} — http://127.0.0.1:{httpd.server_address[1]}/  (ctrl-c to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[styre] stopped.")
    finally:
        httpd.server_close()
    return 0
