"""Verification: the gate commands, and the test-tampering guard.

Agents game weak tests — deleted assertions, skip markers, hard-coded returns. The gate is
the arbiter of a phase, and this guard catches the cheapest way of making a red suite green.
"""
import re

from styre.gitops import stage_all, staged_diff
from styre.process import run
from styre.timeline import Timeline

TEST_PATH = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*\.(test|spec)\.[cm]?[jt]sx?$)")
SKIP_RE = re.compile(r"pytest\.(mark\.)?(skip|xfail)|unittest\.skip"
                     r"|\b(it|test|describe)\.(skip|only)\(|\bxit\(|\bxdescribe\(")
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
    for cmd in phase.gate:
        with tl.span("gate", phase=phase_n, step=step, command=cmd) as end:
            rc, out = run(cmd, shell=True, log=log, timeout=gate_timeout or None)
            end["rc"] = rc
        if rc != 0:
            return (f"gate failed: {cmd[:60]}",
                    f"Gate command failed: `{cmd}` (exit code {rc}). Output tail:\n{out[-6000:]}")
    if not allow_test_changes:
        stage_all()
        problem = test_tampering(staged_diff())
        tl.event("guard_result", phase=phase_n, step=step, ok=problem is None, problem=problem)
        if problem:
            return "test guard: skipped or removed tests", "Test guard: " + problem
    return None
