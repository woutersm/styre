"""Preflight and the phase loop.

One fresh pi process per phase, serially. The agent's claim of success is never trusted:
after it stops, the orchestrator runs the gate itself and inspects the staged diff. Nothing
is committed on a red gate.
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from styre import __version__
from styre.agents import write_agents_file
from styre.config import AGENTS, DECISIONS, PI, WORK, RunOptions
from styre.design import parse_phases, phase_context
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
from styre.review import describe_review
from styre.rundir import RunDir, clear_inbox, collect, latest_run, new_run, open_run
from styre.state import read_state, state_problem
from styre.summarize import read_jsonl, summarize
from styre.timeline import Timeline
from styre.touch import touch


class PreflightError(Exception):
    """A condition that stops the run before any phase starts."""


@dataclass
class Ctx:
    """Everything the phase loop threads through: what is being run, where, and how.

    Built once in `orchestrate()` and passed down whole, so a function that needs the run
    directory, the options and the timeline takes one argument rather than six.
    """

    design_path: str
    opts: RunOptions
    run: RunDir
    tl: Timeline
    text: str = field(default="", init=False)
    phases: list = field(default_factory=list, init=False)

    def __post_init__(self):
        self.reload()

    def reload(self):
        """(Re-)read the design off disk.

        Called again after a Claude touch patches it, so every later phase gets the fixed
        text. A patch that adds or loses phases is ignored: the shape of a run is fixed when
        it starts, and renumbering it halfway through is not a thing to discover at 3am.
        """
        text = Path(self.design_path).read_text(encoding="utf-8")
        phases = parse_phases(text)
        if self.phases and len(phases) != len(self.phases):
            print("[warn] the patched design has a different number of phases; keeping the "
                  "one the run started with.", flush=True)
            return
        self.text, self.phases = text, phases

    def phase(self, n):
        return self.phases[n - 1]

    def context(self, n):
        """The design excerpt phase n's prompt gets."""
        return phase_context(self.text, self.phases, n)


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


def run_phase(ctx, n):
    """Run one phase to a verdict, committing it if everything passes.

    Returns the reason it stopped, or None when it was committed. Everything else worth
    knowing about the phase — durations, rounds, the sha, what the agent claimed — is in
    the timeline, measured rather than reported, and `styre summarize` reads it back.
    """
    phase, run, opts, tl = ctx.phase(n), ctx.run, ctx.opts, ctx.tl
    print(f"[{datetime.now():%H:%M}] {phase.title}", flush=True)
    log, events = run.log(n), run.events(n)

    # Notes are written for the next phase only and are consumed here, so they never pile
    # up in later prompts. They are read from this run's directory, so a new run starts with
    # none and a resume gets exactly the notes the phase before it wrote. The decisions log
    # is written by the agent but never read back to one — see build_prompt.
    previous = run.notes(n - 1)
    notes = previous.read_text(encoding="utf-8").strip() if previous.exists() else ""
    prompt = run.prompt(n)
    prompt.write_text(build_prompt(ctx.context(n), n, phase, notes), encoding="utf-8")

    rounds, why, state = 0, None, None
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
            rc = stream_pi(cmd, timeout=opts.timeout or None, log=log, events=events,
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
            sha = head_sha()
            tl.event("commit", phase=n, sha=sha, subject=phase.title)
            print(f"    ✓ committed {sha[:7]}  {phase.title}", flush=True)

    tl.event("phase_end", phase=n, title=phase.title,
             status="committed" if why is None else "stopped",
             reason=why, rounds=rounds,
             fix_rounds_self=(state or {}).get("fix_rounds_self"),
             unmet_criteria=list((state or {}).get("unmet_criteria") or []))
    return why


def pi_version():
    """What pi reports as its version, or None. Recorded once per run: an overnight failure
    is worth being able to pin to a version afterwards."""
    rc, out = run_command([PI[0], "--version"], timeout=30)
    return out.strip().splitlines()[0] if rc == 0 and out.strip() else None


def _escalate(ctx, n, why):
    """After run_phase() stops, give Claude one turn at the phase before giving up on it.

    One turn, ever: a gate that resists both the local model's own retries and Claude is not
    a capability gap to push through further, it needs a person. Whether the phase has had
    its turn is read off the timeline rather than a bookkeeping file of its own — the touch
    events are already there, and a resumed run appends to the same timeline it reads.
    """
    if any(e.get("event") == "touch_start" and e.get("phase") == n
           for e in read_jsonl(ctx.run.timeline)):
        print(f"    phase {n} has already had its Claude touch — stopping for a human, not "
              "trying again automatically.", flush=True)
        return why
    print(f"    phase {n} stopped ({why}); handing it to Claude...", flush=True)
    return touch(ctx, n, why)


def orchestrate(design_path, opts, run):
    """Run every phase from --from-phase on. Returns the process exit code."""
    tl = Timeline(run.timeline)
    ctx = Ctx(design_path=design_path, opts=opts, run=run, tl=tl)
    tl.event("run_start", run=run.id, styre=__version__, design=str(design_path),
             design_sha256=hashlib.sha256(ctx.text.encode("utf-8")).hexdigest()[:16],
             templates=template_hash(), pi_version=pi_version(), branch=current_branch(),
             phases=len(ctx.phases), from_phase=opts.from_phase, retries=opts.retries)

    # The initial review: what already exists in the repo that each phase's prose names,
    # computed once before any phase runs and written into the run directory rather than
    # requiring a separate call to remember to make. Deterministic, no model call, cheap —
    # unlike a Claude touch, this runs every time, on by default.
    run.review.write_text(f"# Review before phase {opts.from_phase}\n\n"
                          f"{describe_review(ctx.phases)}\n", encoding="utf-8")
    print(f"[styre] review written to {run.review}", flush=True)

    committed, stopped = 0, None
    for n in range(opts.from_phase, len(ctx.phases) + 1):
        why = run_phase(ctx, n)
        if why is not None and opts.claude_touch:
            why = _escalate(ctx, n, why)
        if why is not None:
            stopped = f"Stopped at phase {n}: {why}. Work is left uncommitted."
            break
        committed += 1
        if n < len(ctx.phases):
            # Re-checked against the repo state phase n just produced: a phase can make a
            # later one's own references newly resolvable, or newly conflicting, in ways
            # the initial review — computed before anything was built — could not see.
            with open(run.review, "a", encoding="utf-8") as f:
                f.write(f"\n# Review after phase {n}\n\n{describe_review(ctx.phases[n:])}\n")

    tl.event("run_end", exit_code=1 if stopped else 0, committed=committed, stopped=stopped)
    # The run's own report is `summarize`'s, read back off the timeline it just wrote: the
    # numbers are measured rather than accumulated as we went, and there is one report
    # format rather than a morning one and an evening one that can disagree.
    print("\n" + summarize(run))
    print(f"[styre] run {run.id}: {run.root}")
    return 1 if stopped else 0
