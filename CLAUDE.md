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
| `styre/cli.py` | Argument parsing, the `check` and `run` subcommands. The `styre` console script points here. |
| `styre/config.py` | Constants (`PI`, `WORK`, `DECISIONS`, `AGENTS`, `EXCLUDES`) and the `RunOptions` bundle. |
| `styre/design.py` | Parsing a design into `Phase` objects; `preamble()` and `phase_context()`; `validate()`; the `check` rendering. |
| `styre/prompts.py` | `build_prompt()` and `fix_prompt()`. |
| `styre/agents.py` | `AGENTS_BODY`, the block written into the target repo's `AGENTS.md`. |
| `styre/process.py` | `run()` for gates, `stream_pi()` for the agent, `render_event()`, `kill_tree()`. |
| `styre/gitops.py` | Every git call. |
| `styre/guard.py` | `verify()` — the gate — and `test_tampering()`. |
| `styre/state.py` | Reading and judging `phaseN.state.json`. |
| `styre/runner.py` | `preflight()` and the phase loop (`run_phase`, `orchestrate`). |
| `orchestrate.py` | Deprecated shim mapping the old single-command form onto the subcommands. |
| `pyproject.toml` | Packaging and the `styre` entry point; ruff and pytest config. No runtime dependencies. |
| `example-design.md` | Two-phase example design (a `wordfreq` CLI; uv, pytest, ruff) for testing. |
| `TODO.md` | Tracked next steps: per-run directories, live-streamed pi output, JSON mode and sessions, a timeline file, and a `summarize` command. |
| `tests/` | pytest suite. `fake_pi.py` is a test double installed on `PATH` as `pi`, so the whole loop runs without a model. |
| `tests/fixtures/*.jsonl` | Real captured pi JSON output: a plain reply, a run with a bash tool call, and a saved session file. Write every parser against these, not against assumptions. |

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
   full — not the other phases' bodies), the accumulated `docs/decisions.md`, the previous
   phase's `notes-next.md`, and this phase's criteria and gate. It points at AGENTS.md rather
   than restating the rules.
2. Start a fresh pi process: `pi -p --mode json @<prompt-file> "Follow the instructions in the
   attached file."` — the constant `PI`, not configurable, under `--timeout` (default 5400 s),
   enforced by a watchdog timer rather than a deadline checked per line: the run that stalls
   a night is the one that stops printing. Output is read line by line. Each raw line is stamped with our own wall-clock time and appended to
   `logs/phaseN.events.jsonl`; the condensed non-thinking rendering goes to the terminal in
   grey and to `logs/phaseN.log`. Keep that split: the log is for reading (a few KB), the
   events file is for parsing (a few hundred KB per phase). Putting raw JSON in the log once
   made it 180 KB with the gate output buried at line 404.
3. The agent ends by writing three files: `docs/decisions.md` (append-only, committed),
   `.styre/notes-next.md` (overwritten, read only by the next phase), and
   `.styre/phaseN.state.json` (`status`, `reason`, `unmet_criteria`, `fix_rounds_self`).
   `DONE` together with a non-empty `unmet_criteria` is rejected as contradictory.
4. On `DONE`, the orchestrator runs each gate command itself (`--gate-timeout`, default 900 s).
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
`.styre/phaseN.prompt.md` — not by the command answering.

```
styre check design.md                  # print phases, criteria, gates; validate; exit
styre run design.md                    # run every phase
styre run design.md --from-phase 2     # resume after a stop
```

Other flags on `run`: `--quiet` (no live echo), `--retries`, `--timeout`, `--gate-timeout`,
`--allow-test-changes`, `--branch` (default `overnight/<design-stem>`), `--allow-dirty`,
`--reset-branch`.

`orchestrate.py` still works and translates the old form onto the subcommands, with a
deprecation notice on stderr.

## Preflight

Before phase 1: the design must parse, `pi` must be on PATH, `AGENTS.md` is written or
refreshed, the working directory must be a git repo with a clean tree, and the run switches to `overnight/<design-name>`. An existing run
branch is checked out, never reset — resetting it would throw away phases an earlier run
committed. Re-running phase 1 over a branch that already holds phase commits warns;
`--reset-branch` is the explicit, destructive opt-in. Orchestrator artifacts and caches are
appended to the exclude file located via `git rev-parse --git-path info/exclude`.

## State on disk (in the target repo)

```
.styre/
  phaseN.prompt.md     builder prompt
  phaseN.fixR.md       fix-round prompt
  phaseN.state.json    status, reason, unmet_criteria, fix_rounds_self
  notes-next.md        one phase's hand-off to the next; overwritten, not appended
  logs/phaseN.log      readable transcript + gate output, appended
  logs/phaseN.events.jsonl  raw pi events, each stamped with its arrival time
  report.md            per-phase outcome summary
docs/decisions.md      append-only decision log, COMMITTED with the code
AGENTS.md              standing instructions for the agent, COMMITTED, styre block only
```

Note that logs append across runs and prompts are overwritten, so two runs cannot currently
be compared. Per-run directories under `.styre/runs/<timestamp>/` are the first item
in `TODO.md`, and the rest of that list depends on them.

## Why it is built this way

- Anthropic, on harnesses for long-running agents: fresh context per unit of work with
  structured handoff files, and structured task state. Agents grade their own work too
  kindly. A separate evaluator agent only pays off when the task sits at the edge of what
  the model can do alone — hence no reviewer agent here.
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

- Serial, one agent per phase. No parallel agents, no reviewer agent.
- The agent's claim of success is never trusted; the gate is the arbiter.
- One commit per phase, no tags — the commit is the rollback point.
- Per-run timeout stays: a hung pi process is the failure that stalls a whole night.
- Fresh pi process per phase. State lives in files and git, not in context.
- Handoff state is split by lifetime: decisions are permanent and committed, notes last one
  phase, status is machine-readable. Nothing inventories the repo — the agent reads the tree.
- The prompt's fixed cost is amortised across phases, so it is worth bytes: the honesty rules
  around `unmet_criteria` earn their space. Trim wording, never a rule.
- Standing rules belong in `AGENTS.md` (pi auto-loads it, fix rounds included); only
  phase-specific material belongs in the prompt.
- The CLI is subcommands (`styre check`, `styre run`), installed as a console script. A new
  verb is a new subcommand, not a flag on `run`.
- The pi invocation is fixed: `pi -p --mode json`, the constant `PI`. No `--pi-cmd`, no
  `--model`, no auto-appended `--no-approve`. Local models only; pi's own settings pick which.
- Never commit on a red gate.
- Cross-platform: pathlib, no POSIX-only shell syntax inside the package. (The end-to-end
  tests' own fixture gate uses `test -f`, so they skip on Windows.)

Parked, ask before adding: reviewer agent, hidden held-out tests, spend/time budgets,
placeholder scan, parallel phases, run notifications.

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
  `PI_CODING_AGENT_SESSION_DIR`, then `sessionDir` in settings.
- Print-mode runs **are** saved as sessions. Files are named `<iso>_<uuid>.jsonl`.
- `--name` / `-n` sets the session display name.
- The default provider is `google`, but the configured default here resolves to a **local
  mlxserve model** (`pi --list-models` offers only mlxserve, 65K context, and no provider keys are
  set). Usage and cost therefore come back as zeros — this project runs local models only, so
  any cost reporting must treat zeros as normal rather than as a parse failure.

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
- **Usage and cost are all zero against a local provider** (the sample above ran on a local
  mlx model). Any cost reporting has to tolerate zeros rather than treat them as an error.

## Prompt size

Measured on the two-phase example (`~/Dev/auto2`, real pi): the phase-1 prompt is ~4.8 KB
after the standing rules moved to `AGENTS.md`, of which ~3.1 KB is the design itself. Per
later phase it grows by ~1.25 KB of accumulated decisions, plus the previous phase's notes
(~1.2 KB, which does not compound).

Note this does not cut tokens per run: pi loads `AGENTS.md` into context anyway, so the
~3.4 KB moved rather than vanished. What it buys is one source of truth, and fix-round runs
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

## Safety

pi has no sandbox and runs commands without asking. Run overnight jobs in an ordinary clone
of the target repo (not a linked worktree), with only the credentials the job needs, and set
a spending limit with the model provider. The orchestrator limits time per run but does not
track spend.

On a per-run timeout the whole process group is killed, not just pi, so tool children do not
survive to hold ports and locks into the next phase.
