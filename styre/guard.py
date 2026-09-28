"""Verification: the gate commands, and the test-tampering guard.

Agents game weak tests — deleted assertions, skip markers, hard-coded returns. The gate is
the arbiter of a phase, and this guard catches the cheapest way of making a red suite green.
"""
import re
import time

from styre.gitops import stage_all, staged_diff
from styre.process import run
from styre.timeline import Timeline

TEST_PATH = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*\.(test|spec)\.[cm]?[jt]sx?$)")
SKIP_RE = re.compile(r"pytest\.(mark\.)?(skip|xfail)|unittest\.skip"
                     r"|\b(it|test|describe)\.(skip|only)\(|\bxit\(|\bxdescribe\(")
GATE_REPORT_CHARS = 8000  # the fix prompt's share for gate output, all failures together
TESTDEF_RE = re.compile(r"^\s*(async\s+)?def\s+test_|^\s*(it|test)\(")


def test_tampering(diff):
    """Return a description if the diff skips tests or removes more test functions than it adds."""
    path_a = path = None
    skips, added, removed = [], 0, 0
    for ln in diff.splitlines():
        if ln.startswith("--- "):
            path_a = ln[6:] if ln.startswith("--- a/") else None
            continue
        if ln.startswith("+++ "):
            path = ln[6:] if ln.startswith("+++ b/") else path_a  # deleted file: use the old path
            continue
        if not path or not TEST_PATH.search(path) or ln[:1] not in ("+", "-"):
            continue
        if ln.startswith("+") and SKIP_RE.search(ln):
            skips.append(f"{path}: {ln[1:].strip()}")
        if TESTDEF_RE.match(ln[1:]):
            added, removed = added + (ln[0] == "+"), removed + (ln[0] == "-")
    problems = []
    if skips:
        problems.append("Tests were skipped or marked xfail:\n" + "\n".join(skips[:20]))
    if removed > added:
        problems.append(f"{removed - added} test function(s) were removed. "
                        "Tests must not be deleted to get a green run.")
    return "\n".join(problems) or None


def verify(phase, log, gate_timeout=None, allow_test_changes=False, timeline=None,
           phase_n=None, step=None):
    """Run the gate and the test guard. Return None when all pass, else (short reason, full report).

    `phase_n` and `step` only tag the timeline events. The reader could infer them from the
    preceding pi_end — the loop is serial — but a record that has to be reconstructed by
    inference is one more thing to get wrong later.
    """
    tl = timeline or Timeline()
    # Every command runs, even after one fails. A gate that stopped at its first red command
    # handed the fix round one failure, and the next gate run found the next — one fix round
    # each, for failures that were all there at once (2026-09-28: `ruff` failed a 3-hour
    # phase, and mypy, the tests and the build had not been run). A whole gate is ~40 s; a
    # fix round is a fresh process re-reading the phase.
    failures = []
    for cmd in phase.gate:
        # Printed before the command runs, finished after it: a gate is the longest silence
        # in a phase — a test suite can hold the terminal for minutes — and an unattended run
        # being watched at 11pm should show what it is waiting on rather than nothing.
        print(f"    $ {cmd}", end="", flush=True)
        started = time.monotonic()
        with tl.span("gate", phase=phase_n, step=step, command=cmd) as end:
            rc, out = run(cmd, shell=True, log=log, timeout=gate_timeout or None)
            end["rc"] = rc
        verdict = "ok" if rc == 0 else f"FAILED (exit {rc})"
        print(f" → {verdict} ({time.monotonic() - started:.1f}s)", flush=True)
        if rc != 0:
            failures.append((cmd, rc, out))
    if failures:
        first = failures[0][0]
        more = f" (+{len(failures) - 1} more)" if len(failures) > 1 else ""
        # The whole report stays near the old single-failure size: each tail is cut to its
        # share, the last lines kept, since a test run's reason is at its end.
        share = max(1500, GATE_REPORT_CHARS // len(failures))
        report = "\n\n".join(
            f"Gate command failed: `{cmd}` (exit code {rc}). Output tail:\n{out[-share:]}"
            for cmd, rc, out in failures)
        if len(failures) > 1:
            report = (f"{len(failures)} of the {len(phase.gate)} gate commands failed. "
                      "Fix all of them.\n\n" + report)
        return f"gate failed: {first[:60]}{more}", report
    if not allow_test_changes:
        stage_all()
        problem = test_tampering(staged_diff())
        tl.event("guard_result", phase=phase_n, step=step, ok=problem is None, problem=problem)
        print(f"    test guard → {'ok' if problem is None else 'REJECTED'}", flush=True)
        if problem:
            return "test guard: skipped or removed tests", "Test guard: " + problem
    return None
