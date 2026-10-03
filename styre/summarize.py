"""`styre summarize`: what happened in a run, read back off the disk.

Deterministic, and deliberately so. It calls no model: counting tokens, measuring durations
and deciding which gate failed are exactly the things an agent's own account gets wrong, and
not trusting that account is the point of the orchestrator.

Three sources, in order of authority: `timeline.jsonl` for what the orchestrator did and how
long it took, `logs/phaseN.events.jsonl` for token usage and failed tool calls, and the
`phaseN.state.json` files for what the agent said about itself. Any of them may be missing —
a run killed at 3am is the one most worth summarising — so every reader degrades to a
partial answer instead of failing.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from styre.process import RELAY_RC
from styre.state import read_state

# A styre_gate that was red this many times in one phase is worth a look in the report.
RED_GATES_WORTH_A_LOOK = 3


def read_jsonl(path):
    """Yield the JSON objects in a file, skipping anything unparseable. A half-written last
    line is normal: the file is appended to while a run is in flight."""
    if not path or not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


def read_events(path):
    """Yield pi's events from one phase's events file.

    Each line is `{"ts": ..., "line": raw}`: our own arrival timestamp wrapped around pi's
    event. The stamp is not read here — nothing in the summary is timed off the event
    stream. Durations come from the timeline, which the orchestrator measures itself.
    """
    for wrapper in read_jsonl(path):
        raw = wrapper.get("line")
        if not isinstance(raw, str):
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue  # not an event: text mode, or pi complaining
        if isinstance(event, dict):
            yield event


def final_usage(path):
    """The usage block of the last `message_end` in a phase's events file, or None."""
    last = None
    for e in read_events(path):
        if e.get("type") == "message_end":
            usage = (e.get("message") or {}).get("usage")
            if isinstance(usage, dict):
                last = usage
    return last


def parse_ts(text):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


@dataclass
class Usage:
    """Token usage for one phase.

    `peak` is the high-water mark of `totalTokens`: the largest context the model was asked
    to hold. It is the number that predicts a phase — measured across twelve phases of one
    real design, wall time ran at about a minute per 1,000 tokens of peak context, and the
    two phases that exceeded 85k were the slowest and the one that timed out. It is also
    what the model host runs out of memory over, long before the advertised window.

    It replaced an `input` column that reported the *last* `input` value. That was wrong:
    `input` is per-step uncached prefill on this provider, not a cumulative total, so the
    last value is one step's tail (1,149 on a phase whose context reached 44,766) and
    neither a sum nor a maximum of anything. `totalTokens` is the measured quantity.

    `output` is summed; `message_update.usage` is cumulative within a step and must never
    be summed, which is why only `message_end` is read. `reasoning` is optional — a
    provider that reports no thinking breakdown leaves it undefined, which is not the same
    as zero, so None survives all the way to the printout.

    `cache_read` is summed rather than taken last, because it is read as a ratio: prompt
    caching is live on this provider, and on a measured phase 403k of the 453k tokens the
    model saw were cache hits on the stable prompt prefix. A collapse in that ratio is the
    signal that a phase's prefix stopped being stable.
    """

    peak: int | None = None
    output: int = 0
    reasoning: int | None = None
    cache_read: int = 0

    def add(self, usage, content=None):
        if usage.get("totalTokens") is not None:
            self.peak = max(self.peak or 0, usage["totalTokens"])   # high-water, not a sum
        self.output += usage.get("output") or 0
        self.cache_read += usage.get("cacheRead") or 0   # summed: a hit rate, not a total
        thought = thinking_tokens(usage, content)
        if thought is not None:
            self.reasoning = (self.reasoning or 0) + thought


def thinking_tokens(usage, content=None):
    """The thinking tokens in one assistant message, or None when nothing says.

    The provider's `usage.reasoning` when it can back it; otherwise the message's output split
    by characters across its thinking, text and tool-call blocks. mlxserve reported `0` on a
    message carrying a 66,781-character thinking block (2026-09-23), so a zero beside
    thinking blocks is not believed. modelhost's figure agreed with the character split within
    4 points on three phases (2026-09-29), so a reported figure is otherwise taken as is."""
    blocks = [b for b in content or [] if isinstance(b, dict)]
    thought = sum(len(b.get("thinking") or "") for b in blocks if b.get("type") == "thinking")
    reported = usage.get("reasoning")
    if reported is not None and (reported or not thought):
        return reported
    if not blocks:
        return reported
    rest = sum(len(b.get("text") or "") for b in blocks if b.get("type") == "text")
    rest += sum(len(json.dumps(b.get("arguments") or {})) for b in blocks
                if b.get("type") == "toolCall")
    output = usage.get("output") or 0
    return round(output * thought / (thought + rest)) if thought else 0


@dataclass
class Phase:
    """One phase, as the files describe it."""

    n: int
    title: str | None = None
    status: str | None = None
    reason: str | None = None
    rounds: int | None = None
    self_rounds: int | None = None
    unmet: list[str] = field(default_factory=list)
    sha: str | None = None
    pi_steps: int = 0
    agent_seconds: float = 0.0
    gate_runs: int = 0
    gate_seconds: float = 0.0
    failed_gates: list[tuple] = field(default_factory=list)   # (step, command, rc)
    pi_failures: list[tuple] = field(default_factory=list)    # (step, rc)
    guard_problems: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    tool_errors: dict = field(default_factory=lambda: defaultdict(int))  # tool name -> count
    agent_gates: list = field(default_factory=list)  # each styre_gate run's `passed`, in order
    relays: list = field(default_factory=list)       # (step, context) per fresh start for context
    resumed: int = 0                                 # fix rounds that continued their session
    compactions_failed: list = field(default_factory=list)  # pi's own error per failed one
    compactions_cancelled: int = 0                   # cancelled by styre's no-compaction extension

    @property
    def name(self):
        return self.title or f"Phase {self.n}"

    @property
    def problems(self):
        """Worth reading about in the morning. A phase that committed cleanly but corrected
        itself several times counts: that gap is the clearest sign of a criterion the design
        states less plainly than its gate enforces, and it is invisible in the table."""
        return bool(self.failed_gates or self.pi_failures or self.guard_problems or self.unmet
                    or (self.status and self.status != "committed")
                    or (self.self_rounds and not self.rounds)
                    or bool(self.tool_errors) or bool(self.relays)
                    or bool(self.compactions_failed))


@dataclass
class Run:
    """A whole run directory, summarised."""

    id: str
    phases: list[Phase] = field(default_factory=list)
    starts: list[dict] = field(default_factory=list)  # one per invocation: a resume appends
    ends: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def first(self):
        return self.starts[0] if self.starts else {}

    @property
    def last(self):
        return self.ends[-1] if self.ends else {}


def phase_of(events, n):
    """The Phase for n, created on first mention. Phases appear in the order they ran."""
    for phase in events:
        if phase.n == n:
            return phase
    phase = Phase(n=n)
    events.append(phase)
    return phase


def read_timeline(run, summary):
    """Fold `timeline.jsonl` into the summary. It is the spine: durations, return codes and
    the commit sha all come from here, measured by the orchestrator rather than reported."""
    for e in read_jsonl(run.timeline):
        kind, n = e.get("event"), e.get("phase")
        if kind == "run_start":
            summary.starts.append(e)
        elif kind == "run_end":
            summary.ends.append(e)
        elif n is None:
            continue
        elif kind == "pi_end":
            phase = phase_of(summary.phases, n)
            phase.pi_steps += 1
            phase.agent_seconds += e.get("seconds") or 0
            phase.resumed += bool(e.get("resumed"))
            # A relay ends its step with RELAY_RC on purpose: a fresh start, not a failure.
            if e.get("rc") and e["rc"] != RELAY_RC:
                phase.pi_failures.append((e.get("step"), e["rc"]))
        elif kind == "relay":
            phase_of(summary.phases, n).relays.append((e.get("step"), e.get("context")))
        elif kind == "gate_end":
            phase = phase_of(summary.phases, n)
            phase.gate_runs += 1
            phase.gate_seconds += e.get("seconds") or 0
            if e.get("rc"):
                phase.failed_gates.append((e.get("step"), e.get("command"), e["rc"]))
        elif kind == "guard_result" and not e.get("ok"):
            phase_of(summary.phases, n).guard_problems.append(e.get("problem") or "rejected")
        elif kind == "commit":
            phase_of(summary.phases, n).sha = e.get("sha")
        elif kind == "phase_end":
            phase = phase_of(summary.phases, n)
            phase.title = e.get("title") or phase.title
            phase.status, phase.reason = e.get("status"), e.get("reason")
            phase.rounds, phase.self_rounds = e.get("rounds"), e.get("fix_rounds_self")
            phase.unmet = list(e.get("unmet_criteria") or [])


def read_phase_events(run, phase):
    """Fold one phase's pi events in: token usage, and tool calls that came back an error."""
    for e in read_events(run.events(phase.n)):
        kind = e.get("type")
        if kind == "tool_execution_end" and e.get("isError"):
            phase.tool_errors[e.get("toolName") or "?"] += 1
        elif kind == "tool_execution_end" and e.get("toolName") == "styre_gate":
            text = "".join(c.get("text", "") for c in (e.get("result") or {}).get("content", [])
                           if isinstance(c, dict))
            try:
                phase.agent_gates.append(bool(json.loads(text)["passed"]))
            except (ValueError, KeyError, TypeError):
                pass
        elif kind == "compaction_end":
            # pi's own compaction. styre cancels it (aborted); a failed one is the 2026-09-28
            # shape — a summary request the model could not finish — and worth reading about.
            if e.get("aborted"):
                phase.compactions_cancelled += 1
            elif e.get("errorMessage"):
                phase.compactions_failed.append(e["errorMessage"])
        elif kind == "message_end":
            message = e.get("message") or {}
            usage = message.get("usage")
            if isinstance(usage, dict):
                phase.usage.add(usage, message.get("content"))


def read_state_files(run, summary):
    """The agent's own account, used only where the timeline is silent — a phase killed
    before it could write a phase_end still left a state file behind."""
    for path in sorted(run.root.glob("phase*.state.json")):
        try:
            n = int(path.name[len("phase"):-len(".state.json")])
        except ValueError:
            continue
        state = read_state(path)
        if not state:
            continue
        phase = phase_of(summary.phases, n)
        if phase.status is None:
            phase.status = f"agent said {state.get('status')}, no phase_end"
            phase.reason = state.get("reason") or None
        if not phase.unmet:
            phase.unmet = [str(u) for u in state.get("unmet_criteria") or []]
        if phase.self_rounds is None:
            phase.self_rounds = state.get("fix_rounds_self")


def collect(run):
    """Read a run directory into a Run. Missing files are recorded, not raised."""
    summary = Run(id=run.id)
    if not run.timeline.exists():
        summary.missing.append("timeline.jsonl: no durations, return codes or commits")
    read_timeline(run, summary)
    read_state_files(run, summary)
    for path in sorted(run.root.glob("logs/phase*.events.jsonl")):
        n = int(path.name[len("phase"):-len(".events.jsonl")])
        phase_of(summary.phases, n)
    summary.phases.sort(key=lambda p: p.n)
    for phase in summary.phases:
        if run.events(phase.n).exists():
            read_phase_events(run, phase)
        else:
            summary.missing.append(f"logs/phase{phase.n}.events.jsonl: no token counts")
    return summary


def oneline(text, limit=200):
    """Flatten a multi-line report onto one line. The full text is in the phase log."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


def unique(items):
    """(item, times) in first-seen order: the same gate or guard failure recurs every fix
    round, and listing it three times says no more than listing it once with a count."""
    counts = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return list(counts.items())


def minutes(seconds, measured=True):
    """Minutes to one decimal. `-` means nothing was measured, which is not `0.0`."""
    return f"{seconds / 60:.1f}" if measured else "-"


def count(n):
    return "n/a" if n is None else f"{n:,}"


def thinking_cell(usage):
    """Thinking tokens with their share of the output: on a local model it is most of it."""
    if usage.reasoning is None:
        return "n/a"
    share = f" ({usage.reasoning / usage.output:.0%})" if usage.output else ""
    return f"{usage.reasoning:,}{share}"


def table(header, rows):
    """A markdown table, padded so it is also readable as plain text in a terminal."""
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]

    def line(cells):
        return "| " + " | ".join(str(c).ljust(w) for c, w in zip(cells, widths)) + " |"

    return "\n".join([line(header), "|" + "|".join("-" * (w + 2) for w in widths) + "|",
                      *(line(r) for r in rows)])


def header_lines(summary):
    first, last = summary.first, summary.last
    # The design and branch are where the run began; the versions are what it last ran on,
    # since a run resumed over days may have been upgraded between invocations.
    latest = summary.starts[-1] if summary.starts else {}
    out = [f"# Run {summary.id}", ""]
    facts = [f"design {first['design']}" if first.get("design") else None,
             f"branch {first['branch']}" if first.get("branch") else None,
             f"pi {latest['pi_version']}" if latest.get("pi_version") else None,
             f"styre {latest['styre']}" if latest.get("styre") else None]
    if any(facts):
        out.append(", ".join(f for f in facts if f))
    started, ended = parse_ts(first.get("ts")), parse_ts(last.get("ts"))
    if started:
        span = f" to {ended:%H:%M}, {(ended - started).total_seconds() / 60:.0f} min" if ended else \
               " (no run_end: the run was killed or is still going)"
        out.append(f"started {started:%Y-%m-%d %H:%M}{span}")
    if last:
        out.append(f"exit {last.get('exit_code')}, {last.get('committed')} phase(s) committed"
                   + (f" — {last['stopped']}" if last.get("stopped") else ""))
    if len(summary.starts) > 1:
        out.append(f"{len(summary.starts)} invocations (resumed): "
                   + ", ".join(f"from phase {s.get('from_phase')}" for s in summary.starts))
    hashes = [f"design {first['design_sha256']}" if first.get("design_sha256") else None,
              f"templates {first['templates']}" if first.get("templates") else None]
    if any(hashes):
        out.append("hashes: " + ", ".join(h for h in hashes if h))
    if summary.missing:
        out += ["", "Incomplete — this run is missing:"] + [f"- {m}" for m in summary.missing]
    return out


def phase_table(summary):
    rows = []
    for p in summary.phases:
        rows.append([p.n, p.name, p.status or "?", (p.sha or "-")[:7],
                     minutes(p.agent_seconds, p.pi_steps),
                     minutes(p.gate_seconds, p.gate_runs),
                     "-" if p.rounds is None else p.rounds,
                     "-" if p.self_rounds is None else p.self_rounds,
                     count(p.usage.peak), count(p.usage.output),
                     thinking_cell(p.usage), count(p.usage.cache_read)])
    total = Usage()
    for p in summary.phases:
        total.output += p.usage.output
        if p.usage.peak is not None:                 # the run's peak is a max, never a sum
            total.peak = max(total.peak or 0, p.usage.peak)
        total.cache_read += p.usage.cache_read
        if p.usage.reasoning is not None:
            total.reasoning = (total.reasoning or 0) + p.usage.reasoning
    rows.append(["", "total", "", "",
                 minutes(sum(p.agent_seconds for p in summary.phases),
                         any(p.pi_steps for p in summary.phases)),
                 minutes(sum(p.gate_seconds for p in summary.phases),
                         any(p.gate_runs for p in summary.phases)),
                 sum(p.rounds or 0 for p in summary.phases),
                 sum(p.self_rounds or 0 for p in summary.phases),
                 count(total.peak), count(total.output), thinking_cell(total),
                 count(total.cache_read)])
    return ["## Phases", "",
            table(["#", "Phase", "Status", "Commit", "Agent min", "Gate min", "Fix", "Self",
                   "Peak ctx", "Output", "Thinking", "Cached"], rows),
            "",
            "Peak ctx is the largest context the model held during the phase, and the "
            "total row is the largest of those, not a sum. It is what a phase costs: "
            "roughly a minute per 1,000 tokens, and what the model host runs out of memory "
            "over. Thinking is the part of output spent reasoning, and its share of the output: "
            "the provider's count, or the thinking blocks' share of the characters where the "
            "provider gives none it can back. `n/a` means neither exists, which is not the "
            "same as none. Cached "
            "is the sum of prompt-cache hits: large is good, and it collapsing means the "
            "prompt prefix stopped being stable."]


def where_to_look(summary):
    """The part worth reading in the morning: everything that did not go straight through."""
    out = ["## Where to look", ""]
    for p in summary.phases:
        if not p.problems:
            continue
        out.append(f"**{p.name}** — {p.status or 'no verdict recorded'}"
                   + (f": {p.reason}" if p.reason else ""))
        for step, command, rc in p.failed_gates:
            out.append(f"- gate failed in {step or 'an unknown step'} (exit {rc}): `{command}`")
        for step, rc in p.pi_failures:
            out.append(f"- pi exited {rc} in {step or 'an unknown step'}"
                       + (" (timeout)" if rc == 124 else ""))
        for problem, times in unique(p.guard_problems):
            out.append(f"- test guard{f' ({times}x)' if times > 1 else ''}: {oneline(problem)}")
        for unmet in p.unmet:
            out.append(f"- unmet criterion: {unmet}")
        # With styre_gate, a red run on the way to green is the workflow; only a gate that
        # stayed red is worth a look. Without it, fix_rounds_self is the agent's own claim.
        red = p.agent_gates.count(False)
        if p.agent_gates and red >= RED_GATES_WORTH_A_LOOK:
            out.append(f"- the agent's own gate was red {red} times before it passed: a criterion "
                       "that is hard to hit, or one the design states less clearly than the gate "
                       "enforces.")
        elif not p.agent_gates and p.self_rounds and not p.rounds:
            out.append(f"- the agent fixed {p.self_rounds} gate failure(s) by itself and the "
                       "orchestrator saw none: a criterion the design states less clearly "
                       "than the gate enforces.")
        for name, n in sorted(p.tool_errors.items()):
            out.append(f"- {n} failed {name} call(s)")
        if p.relays:
            peaks = ", ".join(f"{c:,}" for _, c in p.relays if c)
            out.append(f"- {len(p.relays)} fresh start(s) because the context outgrew its budget"
                       + (f" (at {peaks} tokens)" if peaks else "")
                       + ": the phase is doing more work than one context holds")
        for message, times in unique(p.compactions_failed):
            out.append(f"- pi's compaction failed{f' ({times}x)' if times > 1 else ''}: {oneline(message)}")
        if p.resumed:
            out.append(f"- {p.resumed} fix round(s) resumed their session instead of starting fresh")
        out.append("")
    if not any(p.problems for p in summary.phases):
        out.append("Nothing to report: every phase went through on the first try.")
    return out


def render(summary):
    """The whole summary as text. Markdown, but meant to read fine in a terminal."""
    blocks = [header_lines(summary), phase_table(summary), where_to_look(summary)]
    return "\n\n".join("\n".join(b).strip("\n") for b in blocks if b).rstrip() + "\n"


def summarize(run):
    """Summarise a run directory: write `summary.md` into it and return the text."""
    text = render(collect(run))
    (run.root / "summary.md").write_text(text, encoding="utf-8")
    return text


def repo_history(runs_dir):
    """Every phase any run in this repository has left events for, as
    (run id, Phase) pairs, oldest run first. For `check`: what phases here have cost, so a
    new design is judged against this repository's own numbers rather than another's."""
    from styre.rundir import RunDir  # a reader of run directories, like the rest of this module
    out = []
    for root in sorted(d for d in runs_dir.glob("*") if d.is_dir()):
        for phase in collect(RunDir(root)).phases:
            if phase.usage.peak:
                out.append((root.name, phase))
    return out


def history_lines(history, budget):
    """`check`'s account of `repo_history`: how big phases here got, and which passed the
    context budget a step now has."""
    if not history:
        return []
    peaks = sorted(p.usage.peak for _, p in history)
    median = peaks[(len(peaks) - 1) // 2]
    run_count = len({run for run, _ in history})
    largest_run, largest = max(history, key=lambda rp: rp[1].usage.peak)
    out = [f"{len(history)} phase(s) in {run_count} run(s): median peak context {median:,}, "
           f"largest {largest.usage.peak:,} ({largest.name}, {largest_run})."]
    if budget:
        over = [(run, p) for run, p in history if p.usage.peak >= budget]
        out.append(f"A step now gets {budget:,} tokens before styre starts it fresh; "
                   f"{len(over)} of these phases went past that" + (":" if over else "."))
        out += [f"  {p.usage.peak:>8,}  {p.name}  ({run})"
                for run, p in sorted(over, key=lambda rp: -rp[1].usage.peak)[:8]]
    return out
