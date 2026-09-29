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
from styre.config import (
    AGENTS,
    DECISIONS,
    MAX_RELAYS,
    PI,
    PI_CONFIG_DIR,
    PI_EXTENSIONS,
    RELAY_FRACTION,
    RESUME_FRACTION,
    WORK,
    RunOptions,
)
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
    work_tree_id,
)
from styre.guard import verify
from styre.process import RELAY_RC, stream_pi
from styre.process import run as run_command
from styre.prompts import (
    build_prompt,
    fix_prompt,
    handoff_prompt,
    relay_prompt,
    resumed_fix_prompt,
    template_hash,
)
from styre.review import describe_review
from styre.rundir import (
    RunDir,
    archive_progress,
    clear_inbox,
    clear_progress,
    collect,
    latest_run,
    new_run,
    newest_session,
    open_run,
    read_progress,
)
from styre.server import provider
from styre.state import read_state, state_problem
from styre.summarize import final_usage, read_jsonl, summarize
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


def open_run_dir(opts, design_path):
    """Pick the directory this run writes into: a new one, the one --run-id names, or, when
    resuming, the latest. Raises PreflightError if --run-id names nothing."""
    if opts.run_id:
        run = open_run(opts.run_id)
        if run is None:
            raise PreflightError(f"No run directory .styre/runs/{opts.run_id}.")
        return run
    if opts.from_phase > 1:
        run = latest_run()
        if run is not None and run_design(run) == Path(design_path).as_posix():
            return open_run(run.id)
        # Only a run of the same design is continued. Resuming into the latest run whatever it
        # ran mixed two designs' phases in one directory: on 2026-09-28 the sources design's
        # phases 2 and 3 appended to the web-edit run's phase2/phase3 event files, and every
        # summary of either run added the other's tokens to its own.
        why = ("there is no earlier run directory" if run is None else
               f"the latest run ({run.id}) ran {run_design(run) or 'an unknown design'}")
        print(f"[warn] resuming, but {why}: starting a new run directory. "
              "The previous phase's notes are lost.", flush=True)
    return new_run()


def run_design(run):
    """The design a run directory was started with, as its first run_start recorded it."""
    for e in read_jsonl(run.timeline):
        if e.get("event") == "run_start":
            return Path(e.get("design") or "").as_posix() or None
    return None


def preflight(design_path, opts):
    """Check the environment, prepare the repository, and return the run directory.

    Raises PreflightError with a message meant for the user.
    """
    if not shutil.which(PI[0]):
        raise PreflightError(f"'{PI[0]}' not found on PATH.")
    if not (PI_CONFIG_DIR / "models.json").is_file():
        raise PreflightError(
            f"No pi config for styre at {PI_CONFIG_DIR}.\n"
            "An unattended run uses its own pi configuration rather than your interactive "
            "one, so a phase never carries packages, tools or writing-style instructions it "
            "has no use for. Create it:\n"
            f"  mkdir -p {PI_CONFIG_DIR}\n"
            f"  cp ~/.config/pi/agent/models.json ~/.config/pi/agent/auth.json {PI_CONFIG_DIR}/\n"
            f"  echo '{{}}' > {PI_CONFIG_DIR}/settings.json\n"
            "Leave packages out of that settings.json, and put no AGENTS.md beside it.")
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

    run = open_run_dir(opts, design_path)
    print(f"[styre] branch {branch}, run {run.id} ({run.root})", flush=True)
    return run


def empty_response(events):
    """True when pi's last message came back with nothing at all: no input, no output.

    This is not the agent failing to follow its contract, it is the provider refusing or
    dropping the request, and the two look identical from here — pi ends the turn and exits
    0 either way. Measured on 2026-09-22: the model host rejected a prefill for memory
    ("predicted peak would exceed prefill safety cap 37.8GB") and returned an empty stream.
    styre reported "no state file written", which sent a human reading the agent's contract
    for two days when the answer was in the model server's log on another machine.
    """
    usage = final_usage(events)
    return bool(usage) and not any(usage.get(k) for k in ("input", "output", "totalTokens"))


def pi_command(run, n, step, prompts, session=None):
    """The pi invocation for one step: the constant PI, where its session lives, the step's
    name, styre's own extensions, and the prompt files, in order.

    `session` resumes that session file (a small fix round); otherwise pi starts a new one in
    the phase's session directory. pi saves every print-mode run as a session, and pointed at
    the run directory each step's transcript lands beside that run's logs.
    """
    sessions = run.sessions(n)
    sessions.mkdir(parents=True, exist_ok=True)
    where = ["--session", Path(session).as_posix()] if session else ["--session-dir", sessions.as_posix()]
    extensions = [arg for path in PI_EXTENSIONS for arg in ("--extension", path.as_posix())]
    files = [f"@{Path(f).as_posix()}" for f in prompts]
    ask = ("Follow the instructions in the attached file." if len(files) == 1 else
           "Follow the instructions in the attached files; the last one says what to do now.")
    return PI + where + ["--name", f"{run.id} phase {n} {step}"] + extensions + files + [ask]


def context_budget():
    """(relay_at, resume_below) in tokens, from the contextWindow of the model styre's pi config
    uses; (None, None) when it names none, which switches both off."""
    window = (provider() or {}).get("context_window")
    if not isinstance(window, int) or window <= 0:
        return None, None
    return int(window * RELAY_FRACTION), int(window * RESUME_FRACTION)


def handoff(ctx, n, step, k, context, relay_at):
    """Before a relay: resume the stopped step's session for one turn that only writes the
    progress file. The step was stopped between two turns, so the conversation is whole and
    still cached; the fresh process then starts from what this one knew. A handoff that fails
    costs nothing but itself — the relay goes ahead with whatever progress file there is."""
    run, opts, tl = ctx.run, ctx.opts, ctx.tl
    session = newest_session(run, n)
    if session is None:
        return
    prompt = run.handoff(n, k)
    prompt.write_text(handoff_prompt(context, relay_at), encoding="utf-8")
    name = f"{step} handoff"
    before = read_progress()
    with tl.span("pi", phase=n, step=name) as end:
        end["rc"] = stream_pi(pi_command(run, n, name, [prompt], session),
                              timeout=opts.timeout or None, log=run.log(n), events=run.events(n),
                              quiet=opts.quiet, done_when=lambda: read_progress() != before)
        end["handoff"] = True
    clear_inbox(n)  # a handoff finishes nothing: a state file written here is not the phase's
    archive_progress(run, n)


def run_phase(ctx, n):
    """Run one phase to a verdict, committing it if everything passes.

    Returns the reason it stopped, or None when it was committed. Everything else worth
    knowing about the phase — durations, rounds, the sha, what the agent claimed — is in
    the timeline, measured rather than reported, and `styre summarize` reads it back.

    A phase is a sequence of pi processes: the builder, then fix rounds after a red gate. Two
    things keep each one's context small (see CLAUDE.md, "Context"):

    - **A relay**: a step whose context passes `relay_at` is stopped between two turns, gets
      one resumed turn to write its progress file (`handoff`), and the phase carries on in a
      fresh process, handed the task and that file.
      It is not a fix round and uses none of `--retries`; MAX_RELAYS bounds it.
    - **A resumed fix round**: when the step that failed the gate ended below `resume_below`,
      the fix round continues that step's own session, which the model host still has cached,
      rather than a fresh process re-reading the phase.
    """
    phase, run, opts, tl = ctx.phase(n), ctx.run, ctx.opts, ctx.tl
    print(f"[{datetime.now():%H:%M}] {phase.title}", flush=True)
    log, events = run.log(n), run.events(n)
    relay_at, resume_below = context_budget()

    # Notes are written for the next phase only and are consumed here, so they never pile
    # up in later prompts. They are read from this run's directory, so a new run starts with
    # none and a resume gets exactly the notes the phase before it wrote. The decisions log
    # is written by the agent but never read back to one — see build_prompt.
    previous = run.notes(n - 1)
    notes = previous.read_text(encoding="utf-8").strip() if previous.exists() else ""
    builder = run.prompt(n)
    builder.write_text(build_prompt(ctx.context(n), n, phase, notes), encoding="utf-8")
    clear_progress()

    task = [builder]          # the prompt files that state the work of the current round
    prompts, session = task, None
    rounds, relays, why, state = 0, 0, None, None
    start_mark = None
    round_relays = 0
    while True:
        clear_inbox(n)
        step = "builder" if rounds == 0 else f"fix {rounds}"
        if round_relays:
            step += f" relay {round_relays}"
        cmd = pi_command(run, n, step, prompts, session)
        stats = {}
        with tl.span("pi", phase=n, step=step) as end:
            rc = stream_pi(cmd, timeout=opts.timeout or None, log=log, events=events,
                           quiet=opts.quiet, relay_at=relay_at, stats=stats)
            end["rc"] = rc
            end["context"] = stats.get("last_context")
            if session:
                end["resumed"] = True
        archive_progress(run, n)
        if rc == RELAY_RC:
            collect(run, n)
            state = read_state(run.state(n))
            if state is None:
                stuck = round_relays and (work_tree_id(), read_progress()) == start_mark
                relays += 1
                round_relays += 1
                tl.event("relay", phase=n, step=step, context=stats.get("last_context"),
                         relay_at=relay_at, relays=relays)
                if stuck:
                    why = (f"fresh start {relays - 1} filled its context to {relay_at:,} tokens "
                           "without changing the tree or its progress file — the phase is "
                           "stuck, or too big for one context: split it")
                    break
                if relays > MAX_RELAYS:
                    why = (f"the context outgrew {relay_at:,} tokens {relays} times; "
                           f"{MAX_RELAYS} fresh starts did not finish the phase — it is too "
                           "big for one phase, split it")
                    break
                print(f"    context {stats.get('last_context', 0):,} ≥ {relay_at:,}: fresh start "
                      f"{relays}", flush=True)
                handoff(ctx, n, step, relays, stats.get("last_context", 0), relay_at)
                # What the fresh start begins from. It must change one of the two to earn
                # another: a phase is bounded by its progress, MAX_RELAYS only backs that up.
                start_mark = (work_tree_id(), read_progress())
                relay = run.relay(n, relays)
                relay.write_text(relay_prompt(n, phase, read_progress(), stats.get("last_context", 0),
                                              relay_at), encoding="utf-8")
                prompts, session = task + [relay], None
                continue
            # The state file is there: the process had finished its work in the turn it was
            # stopped after. Judge it like any other finished step.
        elif rc != 0:
            why = f"pi exited with {rc}" + (" (timeout)" if rc == 124 else "")
            break
        else:
            collect(run, n)
            state = read_state(run.state(n))
        problem = state_problem(state)
        if problem:
            why = problem
            if empty_response(events):
                why = ("the model returned an empty response (0 tokens in and out) — the "
                       "provider refused or dropped the request, so check the model host's "
                       f"log, not the agent. It then wrote nothing: {problem}")
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
        round_relays = 0
        fix = run.fix(n, rounds)
        last = newest_session(run, n)
        context = stats.get("last_context")
        if resume_below and context and context < resume_below and last is not None:
            fix.write_text(resumed_fix_prompt(n, phase, full), encoding="utf-8")
            task, prompts, session = [fix], [fix], last
            how = f"resuming the session at {context:,} tokens"
        else:
            fix.write_text(fix_prompt(n, phase, full, read_progress()), encoding="utf-8")
            task, prompts, session = [builder, fix], [builder, fix], None
            how = "fresh process"
        print(f"    fix round {rounds} of {opts.retries} ({how})", flush=True)

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
             reason=why, rounds=rounds, relays=relays,
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
             pi_config=str(PI_CONFIG_DIR),
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
