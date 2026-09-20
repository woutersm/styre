"""Preflight and the phase loop.

One fresh pi process per phase, serially. The agent's claim of success is never trusted:
after it stops, the orchestrator runs the gate itself and inspects the staged diff. Nothing
is committed on a red gate.
"""
from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from styre import __version__
from styre.agents import write_agents_file
from styre.config import AGENTS, DECISIONS, PI, WORK
from styre.design import phase_context
from styre.gitops import (
    add_excludes,
    branch_exists,
    commit,
    current_branch,
    git,
    has_staged_changes,
    head_sha,
    in_repo,
    is_dirty,
    phase_commits,
    stage_all,
)
from styre.guard import verify
from styre.process import run as run_command
from styre.process import stream_pi
from styre.prompts import build_prompt, fix_prompt, template_hash
from styre.rundir import clear_inbox, collect, latest_run, new_run, open_run
from styre.state import read_state, state_problem
from styre.timeline import Timeline


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


def open_run_dir(opts):
    """Pick the directory this run writes into: a new one, the one --run-id names, or, when
    resuming, the latest. Raises PreflightError if --run-id names nothing."""
    if opts.run_id:
        run = open_run(opts.run_id)
        if run is None:
            raise PreflightError(f"No run directory .styre/runs/{opts.run_id}.")
        return run
    if opts.from_phase > 1:
        run = latest_run()
        if run is not None:
            return open_run(run.id)
        print("[warn] resuming, but there is no earlier run directory: starting a new one. "
              "The previous phase's notes are lost.", flush=True)
    return new_run()


def preflight(design_path, opts):
    """Check the environment, prepare the repository, and return the run directory.

    Raises PreflightError with a message meant for the user.
    """
    if not shutil.which(PI[0]):
        raise PreflightError(f"'{PI[0]}' not found on PATH.")
    if not in_repo():
        raise PreflightError("Run this from inside a git repository.")

    WORK.mkdir(parents=True, exist_ok=True)
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

    run = open_run_dir(opts)
    print(f"[styre] branch {branch}, run {run.id} ({run.root})", flush=True)
    return run


def run_phase(context, n, phase, opts, run, tl):
    """Run one phase to a verdict, committing it if everything passes."""
    print(f"[{datetime.now():%H:%M}] {phase.title}", flush=True)
    log, events = run.log(n), run.events(n)

    # Decisions accumulate across the whole run; notes are written for the next phase only
    # and are consumed here, so they never pile up in later prompts. They are read from this
    # run's directory, so a new run starts with none and a resume gets exactly the notes the
    # phase before it wrote.
    previous = run.notes(n - 1)
    notes = previous.read_text(encoding="utf-8").strip() if previous.exists() else ""
    prompt = run.prompt(n)
    prompt.write_text(build_prompt(context, n, phase, DECISIONS.read_text(encoding="utf-8").strip(), notes),
                      encoding="utf-8")

    start, rounds, why, state = time.time(), 0, None, None
    while True:
        clear_inbox(n)
        step = "builder" if rounds == 0 else f"fix {rounds}"
        # pi saves every print-mode run as a session. Pointed at the run directory, each
        # step's transcript lands beside that run's logs instead of in the user's own
        # session store, and --name says which step wrote it.
        sessions = run.sessions(n)
        sessions.mkdir(parents=True, exist_ok=True)
        cmd = PI + ["--session-dir", sessions.as_posix(),
                    "--name", f"{run.id} phase {n} {step}",
                    f"@{prompt.as_posix()}", "Follow the instructions in the attached file."]
        with tl.span("pi", phase=n, step=step) as end:
            rc, _ = stream_pi(cmd, timeout=opts.timeout or None, log=log, events=events,
                              quiet=opts.quiet)
            end["rc"] = rc
        if rc != 0:
            why = f"pi exited with {rc}" + (" (timeout)" if rc == 124 else "")
            break
        collect(run, n)
        state = read_state(run.state(n))
        problem = state_problem(state)
        if problem:
            why = problem
            break
        failure = verify(phase, log, gate_timeout=opts.gate_timeout,
                         allow_test_changes=opts.allow_test_changes, timeline=tl,
                         phase_n=n, step=step)
        if failure is None:
            break
        short, full = failure
        print(f"    verification failed, {short}", flush=True)
        if rounds >= opts.retries:
            why = f"{short}, still failing after {rounds} fix rounds"
            break
        rounds += 1
        print(f"    fix round {rounds} of {opts.retries}", flush=True)
        prompt = run.fix(n, rounds)
        prompt.write_text(fix_prompt(n, phase, full), encoding="utf-8")

    if why is None:
        stage_all()
        if not has_staged_changes():
            why = "gate passed but the phase changed nothing (no staged diff)"
        else:
            commit(phase.title)
            tl.event("commit", phase=n, sha=head_sha(), subject=phase.title)

    tl.event("phase_end", phase=n, title=phase.title,
             status="committed" if why is None else "stopped",
             reason=why, rounds=rounds,
             fix_rounds_self=(state or {}).get("fix_rounds_self"),
             unmet_criteria=list((state or {}).get("unmet_criteria") or []))

    return PhaseResult(
        n=n, title=phase.title, why=why, rounds=rounds,
        self_rounds=(state or {}).get("fix_rounds_self"),
        minutes=round((time.time() - start) / 60, 1),
        unmet=list((state or {}).get("unmet_criteria") or []),
        log=log,
    )


def pi_version():
    """What pi reports as its version, or None. Recorded once per run: an overnight failure
    is worth being able to pin to a version afterwards."""
    rc, out = run_command([PI[0], "--version"], timeout=30)
    return out.strip().splitlines()[0] if rc == 0 and out.strip() else None


def orchestrate(design_path, phases, opts, run):
    """Run every phase from --from-phase on. Returns the process exit code."""
    text = Path(design_path).read_text(encoding="utf-8")
    lines, stopped = [f"# Overnight run {run.id}", ""], None

    tl = Timeline(run.timeline)
    tl.event("run_start", run=run.id, styre=__version__, design=str(design_path),
             design_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
             templates=template_hash(), pi_version=pi_version(), branch=current_branch(),
             phases=len(phases), from_phase=opts.from_phase, retries=opts.retries)

    committed = 0
    for n, phase in enumerate(phases, 1):
        if n < opts.from_phase:
            continue
        result = run_phase(phase_context(text, phases, n), n, phase, opts, run, tl)
        committed += result.why is None
        lines += result.summary()
        if result.why is not None:
            stopped = (f"Stopped at phase {n}: {result.why}. "
                       f"Work is left uncommitted. Log: {result.log}")
            break

    if stopped:
        lines += ["", stopped]
    text = "\n".join(lines) + "\n"
    run.report.write_text(text, encoding="utf-8")
    print("\n" + text)
    tl.event("run_end", exit_code=1 if stopped else 0, committed=committed, stopped=stopped)
    return 1 if stopped else 0
