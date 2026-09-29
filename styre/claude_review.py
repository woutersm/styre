"""Claude's review of a finished run: quality control by a stronger model, after the gate.

Every phase that committed passed its gate — but the local model wrote the tests that gate
runs, from its own reading of the design, so a green gate proves it agrees with itself. The
EditTodo bug of 2026-09-27 shipped behind such a gate and was found by reading the code.
This is that reading, done once per run instead of by hand in the morning.

It judges and never acts: one `claude -p` over the whole run's diff, with read-only tools
(`CLAUDE_REVIEW`; a write was refused when this was verified live, 2026-09-29), and its
answer is written to `<run>/claude-review.md`. Nothing is changed, committed or re-run on
its account — what to fix, and whether to merge, stays a human's call. That is the
difference from a Claude touch, which writes code but only at a stuck phase.

Off unless `run --claude-review` is passed, or `styre claude-review` is run on a finished
run: it is automatic spend, bounded by REVIEW_BUDGET_USD and REVIEW_TIMEOUT.
"""
from __future__ import annotations

import json
import re

from styre.process import run as run_command
from styre.summarize import read_jsonl

REVIEW_BUDGET_USD = 5
REVIEW_TIMEOUT = 1800
# Read-only: the file tools that cannot write, and git's reading subcommands. Verified against
# the real CLI on 2026-09-29: `touch` through Bash came back in `permission_denials`, no file.
CLAUDE_REVIEW = ["claude", "-p", "--output-format", "json",
                 "--max-budget-usd", str(REVIEW_BUDGET_USD),
                 "--tools", "Read,Grep,Glob,Bash",
                 "--allowedTools", "Read", "Grep", "Glob",
                 "Bash(git log:*)", "Bash(git diff:*)", "Bash(git show:*)"]
VERDICT_RE = re.compile(r"(?m)^#\s*Verdict:\s*(.+?)\s*$")


def commit_range(run):
    """(base, head) of the commits this run made: the parent of its first phase commit, and
    its last. None when it committed nothing."""
    shas = [e["sha"] for e in read_jsonl(run.timeline)
            if e.get("event") == "commit" and e.get("sha")]
    return (f"{shas[0]}^", shas[-1]) if shas else None


def design_of(run):
    """The design path the run's first invocation recorded, or None."""
    for e in read_jsonl(run.timeline):
        if e.get("event") == "run_start" and e.get("design"):
            return e["design"]
    return None


def review_prompt(run, design, base, head):
    return f"""You are the quality control for work a local model did unattended, one phase at a
time, under an orchestrator. Every phase passed its gate — lint, types, tests — but the local
model wrote those tests itself, so a green gate only proves it agrees with itself. Your job is
what the gate cannot do. You can read files and run `git log`, `git diff` and `git show`; you
cannot change anything, and must not try.

- The design it built from: `{design}`. Each "## Phase N" section is one commit.
- The commits: `git log --oneline {base}..{head}`; the change: `git diff {base}..{head}`.
- The run's own report: `{run.root / 'summary.md'}`. Phases that relayed, needed fix rounds or
  corrected themselves often are where to look hardest.

For each phase, check:
1. Does the code do what the phase's exit criteria *mean*, not only what its tests assert?
2. Tests that prove little: no real assertion, asserting on a mock, expectations copied from the
   implementation, the one case the design called out left untested.
3. Bugs the tests miss: the edge cases the design names (time zones, empty input, errors, the
   second run), wrong error handling, personal data or secrets reaching a log.
4. What does not belong: dead code, a duplicated helper, a second way of doing what the repo
   already does one way, anything the design did not ask for.

Read narrowly: the diff first, then only the files a finding needs. Do not report style that a
linter enforces. If nothing is worth fixing, say so — an empty list is a valid review.

Answer with this markdown and nothing else:

# Verdict: MERGE | FIX FIRST | REDO
One or two sentences: why.

## Findings
Most severe first, at most 15. Each one line:
- **bug|risk|cleanup** · `path:line` · what is wrong · why the gate missed it · the fix, in one sentence

## For the next design
What the design could have said to prevent the worst finding, if anything. One paragraph.
"""


def claude_review(run, timeline, log=None):
    """Review the run's commits; write `<run>/claude-review.md`. Returns the verdict line, or a
    short reason there is none. Never raises for a failed call: the run already happened."""
    span = commit_range(run)
    design = design_of(run)
    if span is None or design is None:
        return "nothing to review: the run committed nothing"
    base, head = span
    print(f"[styre] Claude reviews {base[:7]}..{head[:7]} (read-only, "
          f"at most ${REVIEW_BUDGET_USD})", flush=True)
    with timeline.span("claude_review", base=base, head=head) as end:
        rc, out = run_command(CLAUDE_REVIEW + ["--", review_prompt(run, design, base, head)],
                              timeout=REVIEW_TIMEOUT, log=log)
        try:
            data = json.loads(out) if rc == 0 else {}
        except json.JSONDecodeError:
            data = {}
        text = data.get("result") or ""
        ok = rc == 0 and not data.get("is_error") and bool(text)
        m = VERDICT_RE.search(text)
        end.update(rc=rc, ok=ok, cost=data.get("total_cost_usd"),
                   verdict=m.group(1) if m else None)
    path = run.root / "claude-review.md"
    if not ok:
        path.write_text(f"# Verdict: none — the review did not complete (exit {rc})\n\n"
                        f"```\n{out[-4000:]}\n```\n", encoding="utf-8")
        return f"the review did not complete (exit {rc}); see {path}"
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    cost = data.get("total_cost_usd")
    verdict = m.group(1) if m else "no verdict line"
    print(f"[styre] Claude's review: {verdict}"
          + (f" (${cost:.2f})" if isinstance(cost, (int, float)) else "")
          + f" — {path}", flush=True)
    return verdict
