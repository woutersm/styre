"""Preflight and the phase loop.

One fresh pi process per phase, serially. The agent's claim of success is never trusted:
after it stops, the orchestrator runs the gate itself and inspects the staged diff. Nothing
is committed on a red gate.
"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from styre.agents import write_agents_file
from styre.config import AGENTS, DECISIONS, PI, WORK
from styre.design import phase_context
from styre.gitops import (
    add_excludes,
    branch_exists,
    commit,
    git,
    has_staged_changes,
    in_repo,
    is_dirty,
    phase_commits,
    stage_all,
)
from styre.guard import verify
from styre.process import stream_pi
from styre.prompts import build_prompt, fix_prompt
from styre.state import read_state, state_problem


class PreflightError(Exception):
    """A condition that stops the run before any phase starts."""


@dataclass
class PhaseResult:
    """What happened in one phase. `why` is None only when the phase was committed."""

    n: int
    title: str
    why: str | None = None
    rounds: int = 0
    self_rounds: int | None = None
    minutes: float = 0.0
    unmet: list[str] = field(default_factory=list)
    log: Path | None = None

    def summary(self):
        extra = f" ({self.self_rounds} self-corrected)" if self.self_rounds else ""
        rounds = f"{self.rounds} fix rounds{extra}"
        if self.why is None:
            return [f"- {self.title}: done, {rounds}, {self.minutes} min"]
        return ([f"- {self.title}: STOPPED, {self.why}, {rounds}, {self.minutes} min"]
                + [f"    unmet: {u}" for u in self.unmet])


def preflight(design_path, opts):
    """Check the environment, prepare the repository, and return the run branch.

    Raises PreflightError with a message meant for the user.
    """
    if not shutil.which(PI[0]):
        raise PreflightError(f"'{PI[0]}' not found on PATH.")
    if not in_repo():
        raise PreflightError("Run this from inside a git repository.")

    (WORK / "logs").mkdir(parents=True, exist_ok=True)
    add_excludes()

    if not opts.allow_dirty and is_dirty():
        raise PreflightError("Working tree is not clean. Commit or stash first (or pass --allow-dirty).")

    branch = opts.branch or f"overnight/{Path(design_path).stem}"
    exists = branch_exists(branch)
    if exists and opts.reset_branch:
        if git("checkout", "-B", branch)[0] != 0:
            raise PreflightError(f"Could not reset branch {branch}.")
    elif exists:
        # Never 'checkout -B' an existing branch: it moves the branch to the current HEAD and
        # throws away the phases an earlier run already committed.
        if git("checkout", branch)[0] != 0:
            raise PreflightError(f"Could not switch to existing branch {branch}.")
        done = phase_commits(branch)
        if opts.from_phase == 1 and done:
            print(f"[warn] {branch} already has {len(done)} phase commit(s) from an earlier run "
                  f"(latest: {done[0]!r}).\n       Phase 1 will build on top of them. Use "
                  f"--from-phase N to resume, --branch to start elsewhere,\n       or "
                  f"--reset-branch to discard them.", flush=True)
    elif git("checkout", "-b", branch)[0] != 0:
        raise PreflightError(f"Could not create branch {branch}.")

    if write_agents_file():
        print(f"[styre] wrote {AGENTS} (the agents' standing instructions)", flush=True)

    DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    DECISIONS.touch()
    return branch


def run_phase(context, n, phase, opts):
    """Run one phase to a verdict, committing it if everything passes."""
    print(f"[{datetime.now():%H:%M}] {phase.title}", flush=True)
    log = WORK / "logs" / f"phase{n}.log"
    events = WORK / "logs" / f"phase{n}.events.jsonl"
    state_file = WORK / f"phase{n}.state.json"
    notes_file = WORK / "notes-next.md"

    # Decisions accumulate across the whole run; notes are written for the next phase only
    # and are consumed here, so they never pile up in later prompts.
    notes = notes_file.read_text(encoding="utf-8").strip() if notes_file.exists() else ""
    prompt = WORK / f"phase{n}.prompt.md"
    prompt.write_text(build_prompt(context, n, phase, DECISIONS.read_text(encoding="utf-8").strip(), notes),
                      encoding="utf-8")

    start, rounds, why, state = time.time(), 0, None, None
    while True:
        state_file.unlink(missing_ok=True)
        notes_file.unlink(missing_ok=True)
        rc, _ = stream_pi(PI + [f"@{prompt.as_posix()}", "Follow the instructions in the attached file."],
                          timeout=opts.timeout or None, log=log, events=events, quiet=opts.quiet)
        if rc != 0:
            why = f"pi exited with {rc}" + (" (timeout)" if rc == 124 else "")
            break
        state = read_state(state_file)
        problem = state_problem(state)
        if problem:
            why = problem
            break
        failure = verify(phase, log, gate_timeout=opts.gate_timeout,
                         allow_test_changes=opts.allow_test_changes)
        if failure is None:
            break
        short, full = failure
        print(f"    verification failed, {short}", flush=True)
        if rounds >= opts.retries:
            why = f"{short}, still failing after {rounds} fix rounds"
            break
        rounds += 1
        print(f"    fix round {rounds} of {opts.retries}", flush=True)
        prompt = WORK / f"phase{n}.fix{rounds}.md"
        prompt.write_text(fix_prompt(n, phase, full), encoding="utf-8")

    if why is None:
        stage_all()
        if not has_staged_changes():
            why = "gate passed but the phase changed nothing (no staged diff)"
        else:
            commit(phase.title)

    return PhaseResult(
        n=n, title=phase.title, why=why, rounds=rounds,
        self_rounds=(state or {}).get("fix_rounds_self"),
        minutes=round((time.time() - start) / 60, 1),
        unmet=list((state or {}).get("unmet_criteria") or []),
        log=log,
    )


def orchestrate(design_path, phases, opts):
    """Run every phase from --from-phase on. Returns the process exit code."""
    text = Path(design_path).read_text(encoding="utf-8")
    lines, stopped = ["# Overnight run", ""], None

    for n, phase in enumerate(phases, 1):
        if n < opts.from_phase:
            continue
        result = run_phase(phase_context(text, phases, n), n, phase, opts)
        lines += result.summary()
        if result.why is not None:
            stopped = (f"Stopped at phase {n}: {result.why}. "
                       f"Work is left uncommitted. Log: {result.log}")
            break

    if stopped:
        lines += ["", stopped]
    text = "\n".join(lines) + "\n"
    (WORK / "report.md").write_text(text, encoding="utf-8")
    print("\n" + text)
    return 1 if stopped else 0
