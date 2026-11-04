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

from styre import __version__, advisor, settings
from styre.acceptance import write as write_acceptance
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
    context_window,
)
from styre.design import parse_phases, phase_context
from styre.gitops import (
    add_excludes,
    branch_exists,
    commit,
    current_branch,
    diff_stat,
    git,
    has_staged_changes,
    head_sha,
    in_repo,
    is_dirty,
    not_at_root,
    phase_commits,
    stage_all,
    work_tree_id,
)
from styre.guard import verify
from styre.process import RELAY_RC, stream_pi
from styre.process import run as run_command
from styre.prompts import (
    advice_prompt,
    build_prompt,
    fix_prompt,
    handoff_prompt,
    relay_prompt,
    resumed_fix_prompt,
    template_hash,
)
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
    start_phase_tools,
)
from styre.state import read_state, state_problem
from styre.summarize import final_usage, read_jsonl, summarize
from styre.timeline import Timeline


class PreflightError(Exception):
    """A condition that stops the run before any phase starts."""


@dataclass
class PhaseResult:
    """The verdict of one attempt of a phase: why it stopped, whether the stop was the
    builder's work (a stall the advisor may take up) or the model host's, the gate's last
    full report, and the counters the next attempt continues from."""

    reason: str | None   # None: committed
    stall: bool          # True for the five stall kinds, False for a host failure
    gate_report: str     # the last gate failure's full report, or ""
    rounds: int          # fix rounds used, counted over every attempt of the phase
    relays: int          # relays used, counted over every attempt of the phase


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
        self.text = Path(self.design_path).read_text(encoding="utf-8")
        self.phases = parse_phases(self.text)

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
    try:
        frontier_command = settings.load()["frontier"]["command"][0]
    except settings.SettingsError as e:
        raise PreflightError(str(e)) from e
    if shutil.which(frontier_command) is None:
        print(f"[warn] Claude Code ('{frontier_command}') is not on PATH: a stall will stop "
              "the run instead of going to the advisor.", flush=True)
    if not (PI_CONFIG_DIR / "models.json").is_file():
        raise PreflightError(
            f"No pi config for styre at {PI_CONFIG_DIR}.\n"
            "An unattended run uses its own pi configuration rather than your interactive "
            "one, so a phase never carries packages, tools or writing-style instructions it "
            "has no use for. Create it:\n"
            f"  mkdir -p {PI_CONFIG_DIR}\n"
            f"  cp ~/.pi/agent/models.json ~/.pi/agent/auth.json {PI_CONFIG_DIR}/\n"
            f"  echo '{{\"defaultProvider\": \"…\", \"defaultModel\": \"…\"}}' "
            f"> {PI_CONFIG_DIR}/settings.json\n"
            "Leave packages out of that settings.json, and put no AGENTS.md beside it. "
            "The README has a complete example for a local model.")
    if not in_repo():
        raise PreflightError("Run this from inside a git repository.")
    if (root := not_at_root()) is not None:
        raise PreflightError(f"Run styre from the repository root, not a subdirectory:\n  cd {root}")

    WORK.mkdir(parents=True, exist_ok=True)
    add_excludes()

    if not opts.allow_dirty and is_dirty():
        raise PreflightError("Working tree is not clean. Commit or stash first (or pass --allow-dirty).")

    branch = opts.branch or f"styre/{Path(design_path).stem}"
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
    window = context_window()
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


def run_phase(ctx, n, advice=None, after=None, part=None, part_count=None):
    """Run one phase to a verdict, committing it if everything passes. Returns the
    `PhaseResult`.

    `advice` (the advisor's text) and `after` (the stalled attempt's `PhaseResult`) make
    this the amended attempt: it starts on the tree as the stalled attempt left it, with the
    advice added to the phase's prompt, and its fix-round and relay numbers continue where
    `after` stopped, so `phase1.fix3.md` follows `phase1.fix2.md`.

    `part` (a `(k, Phase)` pair) runs part `k` of a split of phase n, in this run only: the
    phase is the part's `Phase`, under the stalled phase's number, with the part's own gate
    and notes. Part 1 keeps the progress file and gets the split notice in an advice file;
    parts after it start clean. `after` still carries the counters from the attempt before.

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

    stall = True          # every stop is a stall until proven to be the host's
    gate_report = ""
    if part is not None:
        # One part of a split phase, running under the stalled phase's number n. Its design
        # excerpt shows the part in place of the phase, so the index stays an honest list.
        k, phase = part
        run, opts, tl = ctx.run, ctx.opts, ctx.tl
        context = phase_context(ctx.text, ctx.phases[:n - 1] + [phase] + ctx.phases[n:], n)
        previous = run.notes(n - 1) if k == 1 else run.notes(n)  # part 1: as phase n did
        notes = previous.read_text(encoding="utf-8").strip() if previous.exists() else ""
        builder = run.split(n, k)
        builder.write_text(build_prompt(context, n, phase, notes), encoding="utf-8")
        if k == 1:
            # The stalled attempt's progress file is its start, like an amend, and the
            # split notice rides in the advice file after the part's own prompt.
            advice_file = run.advice(n)
            text = (f"The phase was split; you build part 1 of {part_count}, {phase.title}. "
                    "The parts after it build the rest.")
            advice_file.write_text(advice_prompt(n, phase, text, read_progress()), encoding="utf-8")
            task = [builder, advice_file]
        else:
            clear_progress()
            task = [builder]
        write_acceptance(phase, Path.cwd())  # the last part writes the phase's tests back
        start_phase_tools(n, phase.gate, opts.gate_timeout)
        prompts, session = task, None
        rounds, relays = after.rounds, after.relays
        first_step = f"split {k}"
        own_rounds, own_relays = 0, 0
    elif advice is not None:
        # The amended attempt. The progress file is its start, not something to clear, and
        # the stalled attempt's uncommitted work is in the tree.
        builder = run.prompt(n)
        advice_file = run.advice(n)
        advice_file.write_text(advice_prompt(n, phase, advice, read_progress()), encoding="utf-8")
        write_acceptance(phase, Path.cwd())  # a difference at phase start is a resume, not an edit
        start_phase_tools(n, phase.gate, opts.gate_timeout)
        task = [builder, advice_file]
        prompts, session = task, None
        rounds, relays = after.rounds, after.relays
        first_step = "advised"
        # The limits count this attempt's own work: `--retries` more fix rounds and
        # MAX_RELAYS more relays on top of what the stalled attempt used.
        own_rounds, own_relays = 0, 0
    else:
        # Notes are written for the next phase only and are consumed here, so they never pile
        # up in later prompts. They are read from this run's directory, so a new run starts with
        # none and a resume gets exactly the notes the phase before it wrote. The decisions log
        # is written by the agent but never read back to one — see build_prompt.
        previous = run.notes(n - 1)
        notes = previous.read_text(encoding="utf-8").strip() if previous.exists() else ""
        builder = run.prompt(n)
        builder.write_text(build_prompt(ctx.context(n), n, phase, notes), encoding="utf-8")
        clear_progress()
        write_acceptance(phase, Path.cwd())  # a difference at phase start is a resume, not an edit
        start_phase_tools(n, phase.gate, opts.gate_timeout)
        task = [builder]          # the prompt files that state the work of the current round
        prompts, session = task, None
        rounds, relays = 0, 0
        own_rounds, own_relays = 0, 0
        first_step = "builder"

    why, state = None, None
    start_mark = None
    round_relays = 0
    while True:
        clear_inbox(n)
        step = first_step if first_step else ("builder" if rounds == 0 else f"fix {rounds}")
        first_step = None
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
                own_relays += 1
                round_relays += 1
                tl.event("relay", phase=n, step=step, context=stats.get("last_context"),
                         relay_at=relay_at, relays=relays)
                if stuck:
                    why = (f"fresh start {relays - 1} filled its context to {relay_at:,} tokens "
                           "without changing the tree or its progress file — the phase is "
                           "stuck, or too big for one context: split it")
                    break
                if own_relays > MAX_RELAYS:
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
            stall = False
            why = f"pi exited with {rc}" + (" (timeout)" if rc == 124 else "")
            break
        else:
            collect(run, n)
            state = read_state(run.state(n))
        problem = state_problem(state)
        if problem:
            why = problem
            if empty_response(events):
                # Nothing in or out: the host, not the agent, is to blame, so no advisor.
                stall = False
                why = ("the model returned an empty response (0 tokens in and out) — the "
                       "provider refused or dropped the request, so check the model host's "
                       f"log, not the agent. It then wrote nothing: {problem}")
            break
        edited = write_acceptance(phase, Path.cwd())
        if edited:
            tl.event("acceptance_restored", phase=n, step=step, paths=edited)
            print(f"    acceptance tests restored: {', '.join(edited)}", flush=True)
        failure = verify(phase, log, gate_timeout=opts.gate_timeout,
                         allow_test_changes=opts.allow_test_changes, timeline=tl,
                         phase_n=n, step=step)
        if failure is None:
            break
        short, full = failure
        gate_report = full
        print(f"    verification failed, {short}", flush=True)
        if own_rounds >= opts.retries:
            why = f"{short}, still failing after {rounds} fix rounds"
            break
        rounds += 1
        own_rounds += 1
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
        why = commit_phase(ctx, n, phase, patched=False)

    tl.event("phase_end", phase=n, title=phase.title,
             status="committed" if why is None else "stopped",
             reason=why, rounds=rounds, relays=relays,
             fix_rounds_self=(state or {}).get("fix_rounds_self"),
             unmet_criteria=list((state or {}).get("unmet_criteria") or []))
    return PhaseResult(reason=why, stall=stall, gate_report=gate_report,
                       rounds=rounds, relays=relays)


def commit_phase(ctx, n, phase, patched=False):
    """Stage and commit a phase whose gate is green. Returns None on the commit, else the
    reason the phase is not committed — the no-staged-diff rule and the `commit` event
    live here, for both the builder's and the advisor's patch paths."""
    tl = ctx.tl
    stage_all()
    if not has_staged_changes():
        return "gate passed but the phase changed nothing (no staged diff)"
    commit(phase.title if not patched else f"{phase.title}\n\nStyre-Advisor: patch")
    sha = head_sha()
    tl.event("commit", phase=n, sha=sha, subject=phase.title, patch=patched)
    print(f"    ✓ committed {sha[:7]}  {phase.title}" + (" (advisor patch)" if patched else ""),
          flush=True)
    return None


def make_stall(ctx, n, result):
    """The advisor's view of phase n's stall: what stopped, what it can read, and where the
    readable log is."""
    return advisor.Stall(n=str(n), phase=ctx.phase(n), context=ctx.context(n),
                         reason=result.reason, progress=read_progress(),
                         gate_report=result.gate_report, diff_stat=diff_stat(),
                         log=ctx.run.log(n).as_posix())


def advise_stall(ctx, n, result, patches):
    """One advisor call about phase n's stall: the call itself and the run's `advice`
    timeline event for it. Returns (Advice, None) when the advisor is agreed, else
    (None, the sentence it failed with). `patch` is offered while the run has made fewer
    than MAX_PATCHES of them; amend, split and stop are always offered."""
    stall = make_stall(ctx, n, result)
    actions = (["amend", "split", "patch", "stop"] if patches < advisor.MAX_PATCHES
               else ["amend", "split", "stop"])
    advice, error = advisor.advise(stall, actions, cwd=Path.cwd(),
                                   timeline=ctx.tl, log_dir=ctx.run.root / "logs")
    ctx.tl.event("advice", phase=n, action=advice.action if advice else None,
                 reason=advice.reason if advice else None, error=error,
                 titles=[p.title for p in advice.phases]
                 if advice is not None and advice.action == "split" else None)
    return advice, error


def pi_version():
    """What pi reports as its version, or None. Recorded once per run: an unattended failure
    is worth being able to pin to a version afterwards."""
    rc, out = run_command([PI[0], "--version"], timeout=30)
    return out.strip().splitlines()[0] if rc == 0 and out.strip() else None


def orchestrate(design_path, opts, run):
    """Run every phase from --from-phase on. Returns the process exit code."""
    tl = Timeline(run.timeline)
    ctx = Ctx(design_path=design_path, opts=opts, run=run, tl=tl)
    tl.event("run_start", run=run.id, styre=__version__, design=str(design_path),
             design_sha256=hashlib.sha256(ctx.text.encode("utf-8")).hexdigest()[:16],
             templates=template_hash(), pi_version=pi_version(), branch=current_branch(),
             pi_config=str(PI_CONFIG_DIR),
             phases=len(ctx.phases), from_phase=opts.from_phase, retries=opts.retries)

    committed, stopped, patches = 0, None, 0
    for n in range(opts.from_phase, len(ctx.phases) + 1):
        result = run_phase(ctx, n)
        if result.reason is None:
            committed += 1
            continue
        if not result.stall:
            # A host failure stops the run as it always has: the advisor is never called.
            stopped = f"Stopped at phase {n}: {result.reason}. Work is left uncommitted."
            break
        advice, error = advise_stall(ctx, n, result, patches)
        if advice is None:
            stopped = (f"Stopped at phase {n}: {result.reason}. The advisor could not be "
                       f"asked: {error} Work is left uncommitted.")
            break
        if advice.action == "stop":
            stopped = (f"Stopped at phase {n}: {result.reason}. The advisor stopped it: "
                       f"{advice.reason} Work is left uncommitted.")
            break
        if advice.action == "patch":
            # The advisor edits the tree itself; the gate, not its answer, decides. No
            # builder fix round after a red patch: the run stops.
            error = advisor.patch(make_stall(ctx, n, result), advice, cwd=Path.cwd(),
                                  timeline=tl, log_dir=run.root / "logs")
            if error is not None:
                stopped = (f"Stopped at phase {n}: {result.reason}. The advisor's patch call "
                           f"failed: {error} Work is left uncommitted.")
                break
            # The advisor may have touched tests: put the approved ones back, then gate.
            edited = write_acceptance(ctx.phase(n), Path.cwd())
            if edited:
                tl.event("acceptance_restored", phase=n, step="patch", paths=edited)
                print(f"    acceptance tests restored: {', '.join(edited)}", flush=True)
            failure = verify(ctx.phase(n), run.log(n), gate_timeout=opts.gate_timeout,
                             allow_test_changes=opts.allow_test_changes, timeline=tl,
                             phase_n=n, step="patch")
            if failure is not None:
                short, _ = failure
                stopped = (f"Stopped at phase {n}: {result.reason}. The advisor's patch left "
                           f"the gate red: {short} Work is left uncommitted.")
                tl.event("phase_end", phase=n, title=ctx.phase(n).title, status="stopped",
                         reason=short, rounds=result.rounds, relays=result.relays,
                         fix_rounds_self=None, unmet_criteria=[])
                break
            why = commit_phase(ctx, n, ctx.phase(n), patched=True)
            tl.event("phase_end", phase=n, title=ctx.phase(n).title,
                     status="committed" if why is None else "stopped",
                     reason=why, rounds=result.rounds, relays=result.relays,
                     fix_rounds_self=None, unmet_criteria=[])
            patches += 1
            if why is None:
                committed += 1
                continue
            stopped = f"Stopped at phase {n}: {why} Work is left uncommitted."
            break
        if advice.action == "split":
            # The parts replace the phase in this run only; the design file is not touched.
            # The last part keeps the phase's acceptance tests, so the earlier parts' gates
            # must not run them: delete the files, the last part writes them back at start.
            for path, _content in ctx.phase(n).acceptance:
                (Path.cwd() / path).unlink(missing_ok=True)
            for k, part_phase in enumerate(advice.phases, 1):
                result = run_phase(ctx, n, part=(k, part_phase), after=result,
                                   part_count=len(advice.phases))
                if result.reason is not None:
                    stopped = (f"Stopped at phase {n} ({part_phase.title}): {result.reason}, "
                               "after the advisor's split. Work is left uncommitted.")
                    break
            if stopped is None:
                committed += len(advice.phases)
                continue
            break
        # `amend`: the phase runs again on the tree as it is, with the advice in its
        # prompt. A second stall of the same phase stops the run; there is no second call.
        result = run_phase(ctx, n, advice=advice.text, after=result)
        if result.reason is None:
            committed += 1
        else:
            stopped = (f"Stopped at phase {n}: {result.reason}, after the advisor's amend. "
                       "Work is left uncommitted.")
            break

    tl.event("run_end", exit_code=1 if stopped else 0, committed=committed, stopped=stopped)
    # The run's own report is `summarize`'s, read back off the timeline it just wrote: the
    # numbers are measured rather than accumulated as we went, and there is one report
    # format rather than two that can disagree.
    print("\n" + summarize(run))
    print(f"[styre] run {run.id}: {run.root}")
    return 1 if stopped else 0
