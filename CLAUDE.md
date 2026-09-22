# styre

An overnight phase orchestrator for the pi coding agent (`@earendil-works/pi-coding-agent`).

Point it at a design document split into phases. It runs one fresh pi process per phase,
serially, unattended. In the morning there is one git commit per phase and logs showing
what happened.

## Goal

Get a multi-phase design implemented without a human in the loop, and without trusting the
agent's own account of its work. The agent says it is done; the orchestrator decides whether
it is, by running the gate commands itself and inspecting the staged diff. Nothing is
committed on a red gate.

## Files

| File | What it is |
| --- | --- |
| `styre/cli.py` | Argument parsing, the `check`, `run` and `summarize` subcommands. The `styre` console script points here. |
| `styre/config.py` | Constants (`PI`, `CLAUDE`, `WORK`, `DECISIONS`, `AGENTS`, `EXCLUDES`) and the `RunOptions` bundle. |
| `styre/design.py` | Parsing a design into `Phase` objects; `preamble()` and `phase_context()`; `validate()`; the `check` rendering. |
| `styre/review.py` | `find_references()` / `describe_review()`: the second half of `check`, and what `run` calls automatically before phase 1 and after every commit. For every backtick-quoted identifier a phase names, greps the target repo's test-shaped files for existing references — the mechanical half of catching a phase that collides with a frozen test fixture, before a run starts rather than after a timeout. |
| `styre/touch.py` | Claude as the escape hatch — see "The supervising layer". `run_claude()`, `touch_prompt()`, `touch()`: one turn at a stuck phase. Invoked only by `runner.py`'s `_escalate()`, only when `--claude-touch` is passed. |
| `styre/prompts.py` | `build_prompt()`, `fix_prompt()`, and `scope_decisions()` — which part of the decisions log belongs to this design. |
| `styre/agents.py` | `AGENTS_BODY`, the block written into the target repo's `AGENTS.md`. |
| `styre/process.py` | `run()` for gates, `stream_pi()` for the agent, `render_event()` / `elapsed()`, `_watch_idle()`, `kill_tree()`. |
| `styre/gitops.py` | Every git call, including `stage()` / `unstage_all()` (one path, and an emptied index, for the touch's separate design-fix commit) alongside `stage_all()`. |
| `styre/guard.py` | `verify()` — the gate — and `test_tampering()`. `TEST_PATH` is also what `review.py` scopes its grep to. |
| `styre/rundir.py` | The per-run directory `.styre/runs/<id>/`: its paths, `latest.txt`, and collecting the agent's two files into it. |
| `styre/state.py` | Reading and judging `phaseN.state.json`. |
| `styre/summarize.py` | Reading a finished run back off disk: the `summarize` subcommand, and the report every `run` prints as it ends. Calls no model. |
| `styre/timeline.py` | `Timeline`: the append-and-flush writer behind `<run>/timeline.jsonl`. |
| `styre/runner.py` | `preflight()`, the `Ctx` bundle the loop is threaded with, the phase loop (`run_phase`, `orchestrate`), and `_escalate()` — the Claude-touch bounding. |
| `orchestrate.py` | Deprecated shim mapping the old single-command form onto the subcommands. |
| `pyproject.toml` | Packaging and the `styre` entry point; ruff and pytest config. No runtime dependencies. |
| `example-design.md` | Two-phase example design (a `wordfreq` CLI; uv, pytest, ruff) for testing. |
| `TODO.md` | Tracked next steps: a pi preflight and an optional pi-written narrative, plus the record of the 2026-09-22 simplification pass. |
| `tests/` | pytest suite. `fake_pi.py` and `fake_claude.py` are test doubles installed on `PATH` as `pi` and `claude`, so the whole loop — including `--claude-touch` — runs without a model. |
| `tests/fixtures/*.jsonl` | Real captured pi JSON output: a plain reply, a run with a bash tool call, a saved session file, and `pi_usage.jsonl` with real token counts. Write every parser against these, not against assumptions. |

The `styre` package is the source of truth for how things behave today.

## Where it runs

styre is a standalone tool. It is not the repo being built. It must be invoked
from inside the *target* git repository — the project the design describes — because it
switches branches and commits there. This directory is not itself a git repo.

## Design file format

Any preamble, then one block per phase:

````markdown
## Phase 1: Title
What to build.

### Exit criteria
- a statement the agent must make true

### Gate
```
uv sync --locked
uv run pytest -q
```
````

Exit criteria are plain prose for the agent. The **gate** is what the orchestrator enforces.
Both are written by the human, in the design. A phase with no criteria list or no gate block
is a hard error.

## What happens per phase

0. Before phase 1, write the styre block into the target repo's `AGENTS.md` (`AGENTS_BODY` /
   `write_agents_file()`). pi discovers that file on its own and loads it into every run, so
   the standing rules, the "what gets checked" explanation and the three-file contract live
   there rather than in each prompt. A pre-existing `AGENTS.md` keeps its own text; only the
   `<!-- styre:begin -->` … `<!-- styre:end -->` block is replaced.
1. Write a prompt containing the design excerpt for this phase (`phase_context()`: the
   preamble, an index of the phase titles with this one marked, and this phase's section in
   full — not the other phases' bodies), this design's own sections of `docs/decisions.md`
   (`scope_decisions()`, see "Prompt size"), the previous phase's `notes-next.md`, and this
   phase's criteria and gate. It points at AGENTS.md rather
   than restating the rules.
2. Start a fresh pi process: `pi -p --mode json --session-dir <run>/sessions/phaseN --name
   "<run-id> phase N <step>" @<prompt-file> "Follow the instructions in the attached file."`
   — the constant `PI` plus the two per-step session flags, under `--timeout` (default 7200 s
   of **silence**, not of total runtime — see "Watching a run"). Output is read line by line.
   Each raw line is stamped with our own wall-clock time and appended to
   `<run>/logs/phaseN.events.jsonl`; the condensed non-thinking rendering goes to the terminal in
   grey and, as it happens, to `<run>/logs/phaseN.log`. Keep that split: the log is for reading
   (a few KB), the events file is for parsing (a few hundred KB per phase). Putting raw JSON in
   the log once made it 180 KB with the gate output buried at line 404.
3. The agent ends by writing three files: `docs/decisions.md` (append-only, committed),
   `.styre/notes-next.md` (overwritten, read only by the next phase), and
   `.styre/phaseN.state.json` (`status`, `reason`, `unmet_criteria`, `fix_rounds_self`).
   `DONE` together with a non-empty `unmet_criteria` is rejected as contradictory. Those two
   short paths are a drop box, not the archive: once pi stops, `rundir.collect()` moves them
   into the run directory as `phaseN.state.json` and `phaseN.notes-next.md`. The agent's
   contract stays a stable path it can be told about in a committed `AGENTS.md`, which cannot
   name a run id.
4. On `DONE`, the orchestrator runs each gate command itself (`--gate-timeout`, default 900 s),
   printing each one before it starts and its verdict and duration after.
5. It then runs a test-tampering guard over the staged diff: added skip/xfail markers, or a
   net removal of test functions, fail the phase. Disable with `--allow-test-changes`.
6. Any failure is fed back to a fresh pi run as a fix prompt, up to `--retries` (default 2).
7. All green → `git commit -m "<phase title>"`. A phase whose gate passes but which staged no
   diff is treated as a failure, not a success — no empty commits. Otherwise the run stops and
   leaves the work uncommitted; `--from-phase N` resumes.

## Usage

Installed with `uv tool install -e .` (or `pip install -e .`); without installing, use
`python -m styre` with the repository on `PYTHONPATH`.

Install editable while this code is still changing. A non-editable `uv tool install` copies a
built wheel, and uv caches that wheel per source path and version, so `--force` — which
reinstalls the tool without rebuilding it — will reuse a wheel from an earlier session when the
version has not changed. This has already cost one overnight run: on 2026-09-20 the gateway run
went out with the pre-scoping prompt builder, 66 KB prompts carrying all fifteen phases, because
`uv tool install --force .` reinstalled the previous evening's wheel. `styre --version` and
`styre check` were both green on it. Verify an install by behaviour — the size and content of
`.styre/runs/<id>/phaseN.prompt.md` — not by the command answering.

**So bump `__version__` in `styre/__init__.py` whenever behaviour changes.** The version is
the cache key, and it is the only thing that makes `--force` actually rebuild. `pyproject.toml`
reads it from the package (`dynamic = ["version"]`), so there is one number, not two that can
drift. Every run records it in `run_start` and every `summary.md` prints it, which is how a
stale install is recognisable in the morning instead of being a mystery.

```
styre check design.md                  # validate; print phases, criteria, gates; then
                                       #   find existing test-file references its prose names
styre run design.md                    # run every phase
styre run design.md --from-phase 2     # resume after a stop, in the latest run directory
styre run design.md --from-phase 2 --run-id 20260920-2330   # ... in a specific one
styre summarize                        # what happened in the last run
styre summarize 20260920-233014        # ... or a named one, by id or by path
```

Other flags on `run`: `--quiet` (no live echo to the terminal; the log is still written
live), `--retries`, `--timeout`, `--gate-timeout`,
`--allow-test-changes`, `--branch` (default `overnight/<design-stem>`), `--allow-dirty`,
`--reset-branch`, `--run-id`, `--claude-touch` (see "The supervising layer" — off by
default, real automatic spend against the `claude` CLI when it is on).

`orchestrate.py` still works and translates the old form onto the subcommands, with a
deprecation notice on stderr.

## Preflight

Before phase 1: the design must parse, `pi` must be on PATH, `AGENTS.md` is written or
refreshed, the working directory must be a git repo with a clean tree, and the run switches to `overnight/<design-name>`. An existing run
branch is checked out, never reset — resetting it would throw away phases an earlier run
committed. Re-running phase 1 over a branch that already holds phase commits warns;
`--reset-branch` is the explicit, destructive opt-in. Orchestrator artifacts and caches are
appended to the exclude file located via `git rev-parse --git-path info/exclude`.

## Watching a run

What reaches a human while a phase is running, and why each piece is there:

```
[19:59] Phase 1: First phase

[+00:00] ⚙ bash ls -la ✓
[+00:14] Added the tokeniser and its tests.

    $ uv run pytest -q → FAILED (exit 1) (12.4s)
    verification failed, gate failed: uv run pytest -q
    fix round 1 of 2
...
    $ uv run pytest -q → ok (11.9s)
    test guard → ok
    ✓ committed c5f8a76  Phase 1: First phase
```

- **`[+MM:SS]`** is our own clock (`process.elapsed()`), reset per pi process, stamped onto
  the lines that open: a tool call and the start of a reply. pi stamps almost nothing itself
  (see the pi reference below), and "how long has this attempt been going" is the question a
  watcher actually has. A fix round starting again at `+00:00` is the intended reading.
- **The gate lines are printed around the command, not after it.** A gate is the longest
  silence in a phase — a real test suite holds the terminal for minutes — so the command goes
  out before it runs and the verdict lands on the same line when it returns. Before this, a
  passing gate printed nothing at all and the terminal simply died for the length of the run.
- **The commit line is the phase's actual result**, with the sha, so the rollback point is on
  screen rather than only in the timeline.
- These three are orchestrator output, not agent output, so `--quiet` does not suppress them;
  `--quiet` silences the agent's own stream. The log file is written either way.

`<run>/logs/phaseN.log` gets the same rendering **as it happens**, so `tail -f` on it follows
a phase in flight. It used to be assembled in memory and written when pi exited, which meant
the one human-readable file was the one you could not watch.

### The timeout is idle, not a deadline

`--timeout` is seconds of silence allowed from pi, not total runtime: `process._watch_idle()`
watches the gap since the last line and kills the process group when it grows past the limit.
A phase that is working and printing is never cut off; the failure being guarded against — a
sleeping model host or a dropped Wi-Fi link leaving pi blocked on a socket, see "Where the
model runs" — is exactly a process that stops printing.

It follows that the limit must stay comfortably longer than the longest single tool call the
agent might make: pi emits nothing between `tool_execution_start` and `tool_execution_end`,
so a 30-minute test suite running inside a phase is indistinguishable from a dead link from
here. That is why the default is hours and not minutes, and why tightening it is not the
free win it looks like.

## State on disk (in the target repo)

```
.styre/
  latest.txt           the id of the most recently opened run (a file, not a symlink: Windows)
  phaseN.state.json    the agent's drop box; moved into the run directory once pi stops
  notes-next.md        the agent's drop box; moved into the run directory once pi stops
  runs/<YYYYmmdd-HHMMSS>/
    phaseN.prompt.md     builder prompt
    phaseN.fixR.md       fix-round prompt
    phaseN.state.json    status, reason, unmet_criteria, fix_rounds_self
    phaseN.notes-next.md that phase's hand-off, read by phase N+1 and nobody else
    logs/phaseN.log      readable transcript + gate output
    logs/phaseN.events.jsonl  raw pi events, each stamped with its arrival time
    sessions/phaseN/<iso>_<uuid>.jsonl  pi's own session per step, named "<run> phase N <step>"
    timeline.jsonl       what the orchestrator did and how long it took
    review.md            the reference cross-check: before phase 1, then after every commit
    summary.md           the run's report, written when the run ends and by `styre summarize`
docs/decisions.md      append-only decision log, COMMITTED with the code, deliberately per
                       project rather than per run; only this design's sections are sent
                       to the agent (scope_decisions)
AGENTS.md              standing instructions for the agent, COMMITTED, styre block only
```

One directory per run, so two runs can be compared instead of overwriting each other.
`styre run` opens a new one and writes its id to `latest.txt`; `--from-phase N` continues in
the latest run (that is how the previous phase's notes are found) and `--run-id` picks
another. Notes are per phase, not one overwritten file: resuming at phase N must read what
phase N-1 handed over even if a later phase already ran and wrote its own.

## The timeline

`<run>/timeline.jsonl` is the orchestrator's own record of a run, one JSON object per line,
appended and flushed as things happen so a killed run still leaves everything up to the
kill. Every line carries `ts` and `event`.

| Event | Fields |
| --- | --- |
| `run_start` | `run`, `styre`, `design`, `design_sha256`, `templates`, `pi_version`, `branch`, `phases`, `from_phase`, `retries` |
| `pi_start` / `pi_end` | `phase`, `step` (`builder` or `fix N`), and on end `seconds`, `rc` |
| `gate_start` / `gate_end` | `command`, and on end `seconds`, `rc` |
| `guard_result` | `ok`, `problem` |
| `commit` | `phase`, `sha`, `subject` |
| `phase_end` | `phase`, `status` (`committed`/`stopped`), `reason`, `rounds`, `fix_rounds_self`, `unmet_criteria` |
| `run_end` | `exit_code`, `committed`, `stopped` |

Everything in it is measured here — durations, return codes, the sha — never taken from the
agent's account of its own work. `Timeline.span()` writes the `_start`/`_end` pair and the
duration, and writes the end event even when the block raises. A `Timeline` with no path
discards its events, so `verify()` can take one without caring whether a run exists.

Two things a reader has to know. A resumed run **appends** to the timeline of the run it
continues, so there is one `run_start` per invocation, not per directory; group by them.
And `guard_result` is absent, not false, when `--allow-test-changes` turned the guard off.

`templates` is a short hash of `prompts.py` plus the `AGENTS.md` block: a run whose prompt
builder changed underneath it is then recognisable afterwards instead of a mystery. That is
the failure the 2026-09-20 gateway run hit — see "Usage" on verifying an install by
behaviour.

## Summarize

`styre summarize [run]` reports what happened, from the files on disk. With no argument it
takes the run `.styre/latest.txt` names; otherwise a run id or a directory path. It prints
the report and writes it to `<run>/summary.md`.

**It calls no model, and must not start.** Counting tokens, measuring durations and deciding
which gate failed are exactly the things an agent's own account gets wrong, and not trusting
that account is the point of the orchestrator. `TODO.md` T8 is where a pi-written narrative
would go: a separate `narrative.md`, labelled as model-written, on top of these numbers.

Three sources, in that order of authority: `timeline.jsonl` for durations, return codes and
shas; `logs/phaseN.events.jsonl` for tokens and failed tool calls; the `phaseN.state.json` files
for the agent's own account, used only where the timeline is silent — a phase killed before
its `phase_end` still left a state file. Any of them may be missing, and each reader
degrades to a partial answer, because a run killed at 3am is the one most worth reading.

Three sections: the header (design, branch, pi and styre versions, wall time, exit code,
the design and template hashes), the per-phase table, and "where to look".

`run` prints it and writes `summary.md` as it ends, so the morning report and the evening
one are the same artifact in the same format. There is no second per-run report to drift
out of step with it: `report.md`, which `run` used to accumulate as it went, is gone.

Things worth keeping right:

- **`-` is not `0.0`.** A dash means nothing was measured; a zero means it was, and was
  quick. Same rule as `n/a` for thinking tokens — absent is not zero.
- **Input is the last value, output is a sum.** pi reports input cumulatively per step. The
  cumulative-usage trap one level down (`message_update.usage`) is avoided by reading only
  `message_end`.
- **"Where to look" includes a phase that committed cleanly** when it self-corrected and the
  orchestrator saw no fix rounds. That gap is the clearest sign of a criterion the design
  states less plainly than its gate enforces, and it is invisible in the table.
- A gate or guard failure recurring every fix round is listed once with a count.
- Tool calls are read only for their **errors**, counted by tool name and surfaced in "where
  to look". Nothing in the summary is timed off the event stream: durations come from the
  timeline, which the orchestrator measures itself. A per-tool duration table paired by
  `toolCallId` was built and then removed — it was a quarter of this module for something
  nobody read at 8am.

## Why it is built this way

- Anthropic, on harnesses for long-running agents: fresh context per unit of work with
  structured handoff files, and structured task state. Agents grade their own work too
  kindly. A separate evaluator agent only pays off when the task sits at the edge of what
  the model can do alone — which is exactly the only place Claude is allowed to show up: a
  phase boundary the local model has already failed at, never a reviewer grading every
  phase. See "The supervising layer."
- OpenAI, on harness engineering and the ExecPlan format: the plan is a living document in
  the repo, restartable from the plan alone, with a decision log, a surprises section, and
  milestones carrying validation commands.
- Ralph-loop practice: hard deterministic gates (tests, typecheck, lint, build) steer an
  agent far more than prompt text does. Cap the iterations. Broken builds compound, so never
  commit on red.
- Agents game weak tests — deleted assertions, skip markers, hard-coded returns. SpecBench
  measured 97% on visible tests against 0% on held-out tests for a hard-coded lookup table.
  Held-out tests kept outside the repo and invoked from a gate command are the strongest
  defence; they are not built.

## Keep it simple

The plainest thing that works, every time. Before adding something, check it is not already
there; before adding an option, check it has more than one sensible value.

- No configuration knob whose only valid value is its default. `--pi-cmd` was removed for
  exactly this: the event parsing requires `--mode json`, so the flag could not legitimately
  be set to anything else. The invocation is the constant `PI` instead.
- No abstraction with a single caller, no framework where a function will do.
- No feature nobody asked for. The parked list stays parked.
- Prefer deleting code to adding a flag that guards it.
- Stdlib only. A dependency has to earn its place against "write the ten lines".

When a simplification and a safety rule conflict, safety wins — the test guard and the gate
are not complexity to be trimmed. Everything else is.

## Decisions that are settled — do not reopen without asking

- Serial: one agent works at a time, pi or Claude, never both at once — no parallel agents.
  Claude gets one turn at a stuck phase and may patch the design and write it; see "The
  supervising layer." (Decided 2026-09-21 — this replaces the earlier blanket "no reviewer
  agent." Collapsed from a two-touch ladder to one touch on 2026-09-22.)
- The agent's claim of success is never trusted; the gate is the arbiter.
- One commit per phase, no tags — the commit is the rollback point.
- Per-run timeout stays: a hung pi process is the failure that stalls a whole night. It is
  measured as idle time, not total runtime (changed 2026-09-22; the code had always been a
  deadline while this file described a watchdog, and the deadline killed productive phases).
- Fresh pi process per phase. State lives in files and git, not in context.
- Handoff state is split by lifetime: decisions are permanent and committed, notes last one
  phase, status is machine-readable. Nothing inventories the repo — the agent reads the tree.
- The decisions log is stored whole and **transmitted scoped**: `docs/decisions.md` stays
  per project and append-only on disk, but a phase prompt carries only the sections whose
  heading matches a phase title in the design being run (2026-09-22). Storage and
  transmission are separate questions; the first bullet is about storage and is unchanged.
- The prompt's fixed cost is amortised across phases, so it is worth bytes: the honesty rules
  around `unmet_criteria` earn their space. Trim wording, never a rule.
- Standing rules belong in `AGENTS.md` (pi auto-loads it, fix rounds included); only
  phase-specific material belongs in the prompt.
- The CLI is subcommands (`styre check`, `styre run`), installed as a console script. A new
  verb is a new subcommand, not a flag on `run` — but a verb that answers the same question
  as an existing one is not a new verb: `styre review` was folded into `check` on
  2026-09-22, since both only ever answered "is this design safe to start tonight".
- One report per run, `summary.md`, computed from the timeline by `summarize`. `run` prints
  it as it ends rather than accumulating a second one of its own.
- One directory per run; the agent's own two output paths stay short and stable, and the
  orchestrator archives them. A committed `AGENTS.md` cannot name a run id, and a long path
  is one more thing for the model to get wrong.
- The pi invocation is fixed: `pi -p --mode json`, the constant `PI`, plus `--session-dir`
  and `--name` computed per step. No `--pi-cmd`, no `--model`, no auto-appended
  `--no-approve`. Local models only; pi's own settings pick which.
- Never commit on a red gate.
- Cross-platform: pathlib, no POSIX-only shell syntax inside the package. (The end-to-end
  tests' own fixture gate uses `test -f`, so they skip on Windows.)

Parked, ask before adding: hidden held-out tests, spend/time budgets, placeholder scan,
parallel phases, run notifications, a run-level circuit breaker on repeated Claude
escalations (considered 2026-09-21, not needed yet).

## pi reference (verified against pi 0.85.1 on 2026-09-19)

pi works here; there is no auth blocker. Do not guess at pi's behavior — run it and look.
Samples of everything below are in `tests/fixtures/`.

Invocation:

- `pi -p "prompt"` is print mode. `@file` arguments work in print mode **and** in
  `--mode json`; the file is inlined into the user message as `<file name="...">...</file>`.
- `--mode json` prints one JSON object per line.
- `--no-approve` exists (`-na`), stopping project-local extensions and settings from being
  trusted automatically. styre does not pass it: the target repo is the user's own.
- `--session-dir <dir>` works, including in print mode. Precedence is `--session-dir`, then
  `PI_CODING_AGENT_SESSION_DIR`, then `sessionDir` in settings. styre passes it per phase,
  so a run's transcripts sit in the run directory rather than the user's session store. pi
  creates the directory if it is missing; styre creates it anyway.
- Print-mode runs **are** saved as sessions. Files are named `<iso>_<uuid>.jsonl`.
- `--name` / `-n` sets the session display name. Re-verified on 2026-09-20: it lands in the
  session file's `session_info.name`, the second line, not in the streamed events.
- The saved session is **not** a substitute for `logs/phaseN.events.jsonl`. It holds the
  conversation, not the event stream, and carries none of our arrival timestamps. It is
  there so pi's own tooling can open a phase.
- The default provider is `google`, but the configured default here resolves to a **local
  mlxserve model** — no provider keys are set and `pi --list-models` offers only mlxserve. Usage and
  cost report as zero, because nothing is being billed. Token counts are real — see "Token
  accounting" below; they were zero until 2026-09-20 for a config reason, not a local-model
  reason. See "Where the model runs": local does not mean same machine.

Event stream, in order: `session` (header), `agent_start`, `turn_start`, then per message
`message_start` / `message_update`* / `message_end`, with
`tool_execution_start` / `tool_execution_update`* / `tool_execution_end` around tool calls,
then `turn_end`, `agent_end`, `agent_settled`. Note `agent_settled` is not in the docs' list.

Timestamps: only the `session` header and the message object inside `message_end` carry one
(the latter as epoch ms). `message_update` and every `tool_execution_*` event carry none,
which is why the orchestrator stamps lines itself as they arrive.

Thinking is separable, at both levels:

- Streaming: `message_update.assistantMessageEvent.type` is one of `thinking_start` /
  `thinking_delta` / `thinking_end`, `text_start` / `text_delta` / `text_end`, or
  `toolcall_start` / `toolcall_delta` / `toolcall_end`, with a `contentIndex`.
- Final: `message_end.message.content` is a list of blocks typed `thinking`
  (field `thinking`, plus `thinkingSignature` and a `redacted` flag), `text`, or `toolCall`.

So a transcript can be reconstructed with thinking dropped. Note that the far bigger size win
is dropping the `*_update` events altogether and keeping `message_end` and
`tool_execution_end` — on the captured tool-call sample that is 22 KB → 5.6 KB (75% off),
with thinking removal worth only another 2% there because the thinking was short. Deduplicate
first, then filter thinking.

Shapes worth knowing:

- `tool_execution_start`: `toolCallId`, `toolName`, `args`.
- `tool_execution_end`: `toolCallId`, `toolName`, `result`, `isError`. Pair events by
  `toolCallId` to get a duration.
- `turn_end` carries `toolResults`; `agent_end` carries `messages` and `willRetry`.
- Usage lives at `message_end.message.usage` as
  `{input, output, cacheRead, cacheWrite, totalTokens, cost: {...}}`. `message_update.usage`
  has the same shape but is cumulative — never sum it.
- `usage.reasoning` is **optional**: thinking tokens, when the provider reports them. It is a
  *subset* of `output` (output already includes it), so non-thinking output for a step is
  `output - (reasoning or 0)`. Providers that expose no reasoning breakdown leave it
  undefined — that is different from `0`, and the two must not be conflated. `cacheWrite1h`
  is similarly Anthropic-only.
- **Cost is zero against the local provider, but token counts are real** — as long as the
  provider is configured for it. See "Token accounting" below; the captured fixtures predate
  the fix and still show zeros, so do not take them as evidence of what the stream contains.

## Prompt size

Measured on the two-phase example (`~/Dev/auto2`, real pi): the phase-1 prompt is ~4.8 KB
after the standing rules moved to `AGENTS.md`, of which ~3.1 KB is the design itself. Per
later phase it grows by ~1.25 KB of accumulated decisions, plus the previous phase's notes
(~1.2 KB, which does not compound).

**The decisions log is scoped to this design.** `docs/decisions.md` is per project, so a
repo that has already run one design accumulates that design's sections too, and all of it
used to ship in every prompt. Measured on a real repo (`app`, 2026-09-22): the log was
29.6 KB, of which 2.6 KB belonged to the design being run. The other 27 KB was a finished
15-phase plan's history. `scope_decisions()` keeps only the sections whose `## Phase N:
Title` heading matches a phase title in this design — the same heading `build_prompt()`
tells the agent to write, so both sides name the same string. `run` prints how much it
dropped, because a section missing from every prompt is otherwise only noticed at 3am.

The risk that buys: a decision from an *earlier, different* design that a later phase
genuinely needs no longer reaches the agent. It is in the committed file, for a human, and
the phase should name it in its own prose if the agent needs it.

A related trap lives in the **design document's preamble**, which ships to every phase: a
line telling the agent to read a reference document. On `app` the preamble said *"The
design means `docs/agent-design.md`. Read it first"*, and phase 3's 2.3 KB body became a
44 KB context — on a 27B local model the request came back with zero tokens. Measured after
scoping the log and deleting that line: phase 3's whole context went 22,500 → 4,200 tokens.
Write phases that are self-contained; a phase that points at a file has an unbounded prompt.

Note the AGENTS.md move does not cut tokens per run: pi loads `AGENTS.md` into context
anyway, so the ~3.4 KB moved rather than vanished. What it buys is one source of truth, and fix-round runs
that now carry the full contract instead of a shortened reminder.

Against the older single-`handoff.md` format that grew ~2.1 KB per phase, this is larger for
a 2–3 phase design and smaller from phase 4 on, and smaller cumulatively from phase 8. Short
designs pay a premium for the fixed instruction block; that is the accepted trade.

Each phase's criteria and gate appear both in the `<design>` block and in the focused section
below it (~0.7 KB). That repetition is deliberate — it states the contract plainly instead of
making the agent find its own phase in the design.

The design block is an excerpt, not the document. On a long plan that is most of the prompt:
on the 63 KB `gateway-todo.md` it takes a phase prompt from ~65 KB to 16–20 KB. The cost is
that **everything in the preamble now ships to every phase**, so a plan should keep its
preamble to what every phase needs. Material for a human after the last phase belongs in its
own file, not in the preamble; it used to be parked there only because anything after the
last `## Phase` heading is folded into that phase.

## Working on this code

- Python stdlib only at runtime. pytest is the one dev dependency; nothing else.
- Keep every existing behavior working.
- One module, one job. A new concern gets a module; it does not get bolted onto `runner.py`.
- `TODO.md` holds the agreed next steps; start there, and do T4 before the others.
- pi is available and authenticated — get real data from it rather than assuming. Capture new
  fixtures into `tests/fixtures/` when a task needs a shape not covered there.
- Run the suite: `uv run --with pytest python -m pytest -q`. The end-to-end tests drive the
  real phase loop against `tests/fake_pi.py`, so a behavior change shows up there. Add a case
  for anything new rather than only testing it by hand.

## Token accounting

Until 2026-09-20 every `usage` block in the event stream read
`{input: 0, output: 0, totalTokens: 0}`, and this file recorded that as a fact about local
providers. It was not. The mlxserve provider block in `~/.config/pi/agent/models.json` declared:

```json
"compat": { "supportsUsageInStreaming": false }
```

so pi streamed without asking for usage and filled in zeros. The server was asked directly and
reports usage perfectly well, in streaming mode too, given
`stream_options: {"include_usage": true}` — along with `time_to_first_token`,
`generation_tokens_per_second` and prefill timings. The flag is now `true`, and a `message_end`
carries real numbers: `{input: 1507, output: 34, cacheRead: 6144, totalTokens: 7685}`.

Note `totalTokens` includes `cacheRead`, and **prompt caching is live on this provider** — 6144
of those 7685 tokens were cache hits on a trivial prompt. That matters for the prompt-scoping
work: a stable prefix is cheap on the second and later phases.

To total a phase, read `<run>/logs/phaseN.events.jsonl` and, over the `message_end` events,
**sum `output` but take the last `input`** — `message_update.usage` is cumulative and must
never be summed (the same trap, one level down). The first `message_end` of a run carries
`None` rather than `0`; that is absent, not zero.

⚠️ `pi_simple.jsonl`, `pi_toolcall.jsonl` and `pi_session.jsonl` were captured before the
fix, so their usage blocks are zeros. A parser written against them must not conclude that
counts are always zero. `pi_usage.jsonl` (captured 2026-09-20, after the fix) is the one
with real numbers: `input 1560, output 23, cacheRead 6144, reasoning 0` and a `model` on
`message_end`. Note this provider *does* report `reasoning`, as a real 0 rather than an
absent field — the "n/a is not 0" rule is for providers that omit it, not this one.

## Where the model runs

Verified 2026-09-20. "Local" here means on the LAN, not on the machine running styre:

| | |
| --- | --- |
| styre and pi | MacBook Air M2 (`Mac14,2`), 192.168.2.22, on Wi-Fi |
| the model | a second Mac, M4 Pro / 48 GB, at `http://192.168.2.31:8000/v1` |

The endpoint is the `mlxserve` provider's `baseUrl` in `~/.config/pi/agent/models.json`; it is
OpenAI-compatible and wants an API key, which pi holds in `auth.json`. That directory, not
`~/.pi/agent`, is pi's config: `~/.zshrc` exports
`PI_CODING_AGENT_DIR=$HOME/.config/pi/agent`. `~/.pi/agent` is the pre-16-September default
and is now dead — its `models.json` still says `supportsUsageInStreaming: false`, lists
different model ids and does not even parse (a trailing comma). Do not read it for anything;
verify which tree is live by `echo $PI_CODING_AGENT_DIR`. Because the export lives in
`.zshrc`, it reaches interactive shells only: a run started from cron or launchd would fall
back to the dead tree. The default resolves to
`arsis-dev/ukisai-Swift-Qwen3.8-27b-MTPLX` (262K context) — confirmed by reading `model` out of
the event stream, not by assuming. Nothing pins it: `settings.json` has no `model` key, so
installing another mlxserve model can silently change what an overnight run gets.

What follows from the split:

- **Inference heat is not on the styre machine.** The Air runs a Python process and pi; the
  fanless chassis is irrelevant to throughput. Thermal headroom is the M4 Pro's problem.
- **Two machines have to stay awake**, and the second one has its own `pmset` settings.
- **The LAN link is a failure mode of its own.** It is Wi-Fi, with LAN round-trips measured at
  30-110 ms and high variance. A dropped link or a sleeping model host leaves pi waiting on a
  socket with nothing to print, which is precisely the case the per-run watchdog covers: no
  output for `--timeout` seconds kills the process group and the phase fails rather than
  hanging until morning.
- Measured throughput on the 2026-09-20 gateway run: **~60 KB of event-log JSON per minute**,
  flat across three phases. A phase's wall time tracks that rate, so a sustained sag means the
  model host is throttling or the link is degrading.

## Safety

pi has no sandbox and runs commands without asking. Run overnight jobs in an ordinary clone
of the target repo (not a linked worktree), with only the credentials the job needs, and set
a spending limit with the model provider. The orchestrator limits time per run but does not
track spend.

On a per-run timeout the whole process group is killed, not just pi, so tool children do not
survive to hold ports and locks into the next phase.

## The supervising layer — Claude as the escape hatch (built 2026-09-21, simplified 2026-09-22)

Decided after a real run: `docs/agent-todo.md`'s Phase 2, in a real target repo, hit a
genuine contradiction between the design and a pre-existing test fixture, and burned 3h40m
before the timeout killed it rather than the agent ever reporting `BLOCKED`. A
higher-capability model (Claude, via Claude Code), reading the logs afterward, diagnosed the
actual conflict in minutes by cross-referencing the design against the repo, then patched the
design by hand — the same thing the reference cross-check does the mechanical half of.
This section
made that process deliberate rather than accidental; it is now built into `styre run` itself,
not an external script — `styre` owns the whole loop, including the Claude calls.

`styre/touch.py` holds the one Claude invocation (`touch()`); the bounding (`_escalate()`)
lives in `runner.py`, beside the rest of the phase loop it extends. `--claude-touch` on `run` turns it on — off by
default, because it is real, automatic spend against the `claude` CLI, and every existing
test (and every run before today) had no reason to expect that. Every phase stop still
behaves exactly as before when the flag is not passed.

**The invocation, verified 2026-09-21, not guessed:** `claude -p --output-format json
--dangerously-skip-permissions "<prompt>"` (the `CLAUDE` constant in `config.py`, the same
shape as `PI`). `--output-format json` gives one parseable object —
`{result, is_error, total_cost_usd, session_id, ...}` — simpler than pi's line stream, no
new parsing infrastructure needed. `--permission-mode acceptEdits` was tried first and
**denies Bash outright** (`permission_denials` in the response, confirmed live); even
`--permission-mode bypassPermissions` was blocked by a classifier when tested from inside a
nested Claude Code session (an artifact of the nesting, not of `claude -p` itself — not
re-verified from a plain, non-nested shell). `--dangerously-skip-permissions` is the flag
that actually works unattended, confirmed by a real Bash tool call completing with
`permission_denials: []`. Anthropic's own help text for it: *"Recommended only for sandboxes
with no internet access"* — styre runs it on the user's own live machine, with full internet
access, which is not that. Accepted anyway, on purpose, after being told this explicitly —
the same kind of risk `pi`'s own lack of a sandbox already carries here (see "Safety").

Three tiers, each trusting the one below only as far as the gate can verify it:

- pi (the local model) is styre's tool for writing a phase.
- styre is Claude's tool for running a gated phase loop.
- Claude, invoked only at a phase boundary, sits above styre and uses it as its tool.

**The gate does not care who wrote the diff.** This is what makes the arrangement safe:
"the agent's claim of success is never trusted, the gate is the arbiter" holds exactly as
written whether "the agent" is a local pi process or Claude itself. Verification never
changes; only who gets a turn at writing the phase does.

**When Claude gets involved: never mid-phase.** styre reads the design once at phase start,
so there is nothing useful to do while pi is actively working — the same reason a live edit
to `docs/` mid-run does not take effect until the next phase. The only sound entry point is
where styre already, unmodified, stops on its own: `BLOCKED`, a timeout, or the gate still
red after `--retries` (default 2, unchanged — a backstop does not make the cheap local path
cheaper to skip).

**One touch per stuck phase, zero on a clean one.** Claude gets a single turn, and in it
does both things the original two-tier ladder split across two calls:

1. If the design itself is wrong — an instruction that contradicts something already in the
   repo, a real ambiguity, a missing pointer — patch the design document. This is the shape
   of the corrections made by hand to a real `agent-todo.md` on 2026-09-21: a test-fixture
   conflict, a `dataclasses.replace` incompatibility, a hard-coded default a later phase
   would have silently broken. `ctx.reload()` re-reads the design, so every *later* phase
   gets the fix too.
2. Implement the phase. `verify()` — the same one pi's diff is held to — decides whether it
   is green. If it is, `commit()` runs, with an `Escalated:` line in the commit message body
   recording that this phase's code was not written by the local model, so the history stays
   honest.
3. If the touch cannot get the gate green, stop and tell a human. A gate that resists both
   the local model's retries and Claude is not a capability gap to push through further; it
   needs a person.

**Why one call and not two.** The original ladder was Touch 1 (review, maybe patch the
design, then hand the phase back to the local model for a fresh attempt) and Touch 2 (write
it directly), with a `touches.json` counter bounding them. It was collapsed on 2026-09-22:
the split was a cost optimisation — spend the cheap local model again before the expensive
one — not a safety property, since `verify()` judges both paths identically. Against that it
cost a counter file, a "design bug or capability gap?" classification the prompt had to ask
for and the code had to branch on, a re-entrant call back into `run_phase()`, and a third
possible outcome to reason about at 3am. The design fix and the implementation now happen in
one process that has already read both.

**Bounding, precisely:** a phase has had its touch if the timeline holds a `touch_start` for
it. No bookkeeping file — the events are already written, and a resumed run appends to the
same timeline it reads, so a resume cannot spend a second touch (see
`test_a_second_stop_on_the_same_phase_does_not_touch_again` in `tests/test_touch.py`). The
design fix is still committed on its own (`Touch: design fix for phase N`), against an
emptied index so a phase that stopped on the test guard cannot ride along with it: a plan
change and a code change are different kinds of change, the same distinction a human made by
hand (`docs/decisions.md`'s own "make doc more clear" commits, kept apart from phase
commits).

**`run` also always runs the mechanical review, on by default, for both halves of "review
and adjustments" — this part needs no flag and costs nothing, unlike a Touch.** Before phase
1 (or `--from-phase N`), `describe_review(phases)` is written to `<run>/review.md`. After
every phase that commits, it runs again for the *remaining* phases against the repo state
that phase just produced, and is appended — a later phase's references can resolve, or
newly conflict, in ways the initial pass could not have seen. Both are `describe_review()`
called directly; no separate command to remember to run.

**Session shape: a fresh, narrowly scoped Claude process per touch, not one long-running
session babysitting a whole night.** Each `claude -p` call is exactly that — a fresh
process, no memory of an earlier one. This mirrors the exact reasoning that gave pi a
fresh process per phase in the first place (see "Why it is built this way"): a single
sprawling supervising conversation accumulating context across many interventions in one run
would reintroduce, one layer up, the problem that design was built to avoid.

**Deliberately not built:** a run-level circuit breaker — see "Decisions that are settled"
and the parked list.

This reopens one settled decision, "no reviewer agent," on purpose, with reasoning, not by
drifting past it. "Decisions that are settled" above reflects the replacement.
