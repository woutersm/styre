# styre

An overnight phase orchestrator for the pi coding agent (`@earendil-works/pi-coding-agent`).

Point it at a design document split into phases. It runs one fresh pi process per phase,
serially, unattended. In the morning there is one git commit per phase and logs showing
what happened.

## Goal and scope

Get a phased design built by a local model without trusting the model's own account of its
work: the agent says it is done, styre decides whether it is, by running the gate commands
itself and inspecting the staged diff. Nothing is committed on a red gate.

styre does only what needs no judgement: run the phases, keep each one's context small, run
the gate, commit, and write down what happened. Everything that needs judgement — writing
the design, deciding what a stop means, reviewing the result — belongs to the person and the
interactive assistant directing the run, as `skill/DIRECTOR.md` sets out. So styre calls no other
model, makes no network request of its own, and has no viewer: `summarize` is how a run is
read.

## Files

| File | What it is |
| --- | --- |
| `styre/cli.py` | The `check`, `run` and `summarize` subcommands; the `styre` console script. |
| `styre/config.py` | Constants (`PI`, `PI_CONFIG_DIR`, `WORK`, `DECISIONS`, `AGENTS`, `EXCLUDES`, the context fractions), `context_window()`, and the `RunOptions` bundle. |
| `styre/design.py` | Parsing a design into `Phase` objects; `phase_context()`; `validate()` (errors) and `advisories()` (warnings); the `check` rendering. |
| `styre/prompts.py` | The phase prompt, the fix-round prompts (fresh and resumed), the handoff and the relay prompt. |
| `styre/agents.py` | `AGENTS_BODY`, the block written into the target repo's `AGENTS.md`. |
| `styre/runner.py` | `preflight()`, the `Ctx` bundle, the phase loop (`run_phase`, `orchestrate`). |
| `styre/process.py` | `run()` for gates and git, `stream_pi()` for the agent (tracks context, stops at a turn end past `relay_at`), the idle watchdog, `kill_tree()`. |
| `styre/guard.py` | `verify()` — the gate — and `test_tampering()`. |
| `styre/gitops.py` | Every git call. |
| `styre/rundir.py` | The per-run directory `.styre/runs/<id>/`: paths, `latest.txt`, collecting the agent's files. |
| `styre/state.py` | Reading and judging `phaseN.state.json`. |
| `styre/timeline.py` | The append-and-flush writer behind `<run>/timeline.jsonl`. |
| `styre/summarize.py` | Reading a run back off disk: `summarize`, and the report `run` prints as it ends. |
| `styre/pi_extensions/` | Passed to every pi process with `--extension`: `cap-output.js`, `no-compaction.js`, `strip-thinking.js`, and `styre-tools.js` (the agent's `styre_gate`, `styre_progress`, `styre_finish`). |
| `skill/DIRECTOR.md` | How a person and an interactive assistant work with styre: five rules. |
| `skill/writing-designs.md` | How to shape a design before a run. For the author — never named in a design (`advisories()` flags it). |
| `TODO.md` | What is left and what is parked. |
| `tests/` | pytest. `fake_pi.py` is installed on `PATH` as `pi`, so the whole loop runs without a model. `tests/fixtures/*.jsonl` are real captured pi output: write parsers against these, not assumptions. |

## Where it runs

From the root of the *target* git repository: styre switches branches and commits there, and
writes `AGENTS.md` and `.styre/` into the directory it starts in. `run` and `check` refuse a
subdirectory.

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

Exit criteria are prose for the agent; the **gate** is what styre enforces. A phase without
either is a hard error. `skill/writing-designs.md` is the shape: how big a phase may be, and where
to cut one so its gate is green on its own work.

## What happens per phase

0. **Preflight**, once: the design parses, `pi` is on PATH, styre's pi config exists, the tree
   is clean, and the run switches to `overnight/<design-name>` — an existing run branch is
   checked out, never reset (`--reset-branch` is the explicit, destructive opt-in). The styre
   block is written into `AGENTS.md`, which pi loads into every run: standing rules live
   there, only phase-specific material goes in the prompt.
1. The prompt: the design's preamble, an index of phase titles, this phase's section in full,
   the previous phase's `notes-next.md`, its criteria and gate. Not `docs/decisions.md`.
2. A fresh pi process (`pi -p --mode json`, the constant `PI`, plus session, name, extension
   and prompt-file flags), under `--timeout`: seconds of **silence**, not of runtime. Raw events
   go to `logs/phaseN.events.jsonl`, a readable rendering to `logs/phaseN.log`.
3. An all-zero usage block on pi's last message stops the phase with "the model returned an
   empty response" — a provider refusing a request looks exactly like an agent ignoring its
   contract otherwise.
4. The agent appends to `docs/decisions.md`, overwrites `.styre/notes-next.md` and calls
   `styre_finish`, which refuses `DONE` unless its last `styre_gate` passed. styre moves both
   files into the run directory.
5. styre runs the gate itself (`--gate-timeout` per command), then the test-tampering guard
   over the staged diff: added skip/xfail markers or a net loss of test functions fail the
   phase (`--allow-test-changes` turns it off).
6. A failure becomes a fix round, up to `--retries`: the whole gate's failures at once, with
   the phase prompt and the progress file — or, when the failed step ended small, resumed in
   its own still-cached session.
7. Green and a non-empty diff → one commit titled with the phase. Otherwise the run stops,
   the work stays uncommitted, and `--from-phase N` resumes in the same run directory when
   the design is the same.

## Keeping a phase's context small

On a local host every token costs prefill and stays for the rest of the phase. Three rules:
keep tokens out at the source; never rewrite history (it invalidates the prompt cache); when a
step fills up, restart it from a file, not a summary.

| Mechanism | What it does |
| --- | --- |
| `cap-output.js` | a `read` returns at most 300 lines, a `bash` its first 60 and last 90, with a note on how to get the rest |
| `no-compaction.js` | cancels pi's compaction, which on a local host is the most expensive thing a phase can do |
| `strip-thinking.js` | drops earlier thinking from every request |
| Progress file | the agent keeps `.styre/progress.md` (Done / Now / Next / Learned) as it goes; handed to every fix round and relay, archived as `phaseN.progress.md` |
| Relay | past `RELAY_FRACTION` (0.75) of the model's `contextWindow`, the step is stopped at a turn end, writes its progress file in one handoff turn, and continues in a fresh process. A fresh start that changes neither the tree nor the progress file stops the phase; `MAX_RELAYS` is the backstop |
| Resumed fix round | below `RESUME_FRACTION` (0.5), a fix round continues the failed step's cached session |

The fractions come from `contextWindow` in styre's pi config; a config naming no default model
switches relay and resume off.

## pi runs under styre's own config

Every pi process gets `PI_CODING_AGENT_DIR=~/.config/pi/styre` (`config.PI_CONFIG_DIR`), and
preflight refuses to start without its `models.json`. An unattended run must not inherit an
interactive setup: once, 47% of a phase's context was another setup's tool schemas and rules.
Keep it lean — `models.json`, `auth.json`, a `settings.json` with no packages, no `AGENTS.md`.
Gate commands and git keep the inherited environment.

## State on disk (in the target repo)

```
.styre/
  latest.txt              the most recently opened run (a file, not a symlink: Windows)
  progress.md, phaseN.state.json, notes-next.md   the agent's drop box, archived per run
  runs/<YYYYmmdd-HHMMSS>/
    phaseN.prompt.md, phaseN.fixR.md     the prompts
    phaseN.state.json, phaseN.notes-next.md, phaseN.progress.md
    logs/phaseN.log, logs/phaseN.events.jsonl
    sessions/phaseN/...   pi's own sessions
    timeline.jsonl        what styre did and when, measured, never the agent's account
    summary.md            the report, written when the run ends and by `styre summarize`
docs/decisions.md         append-only, committed; written by the agent, never read back to one
AGENTS.md                 committed; only the styre block is managed
```

## Decisions that are settled — ask before reopening

- **No judgement in styre.** It calls no model and makes no network request. Reviewing a run,
  deciding what a stop means and fixing a design are the director's (`skill/DIRECTOR.md`). Claude
  as an automatic escape hatch, an automatic Claude review, the design-to-repo cross-check
  and the web viewer were built and removed on 2026-10-03 for this reason.
- **The agent's claim of success is never trusted**; the gate is the arbiter. Never commit
  on a red gate. The test guard and the gate are not complexity to trim.
- **One commit per phase**, no tags: the commit is the rollback point.
- **Serial, one fresh pi process per phase.** State lives in files and git, not in context —
  within a phase too: a step that outgrows its budget continues from its progress file.
- **Handoff state is split by lifetime**: decisions permanent and committed, notes one
  phase, progress one phase's steps, status machine-readable. Nothing inventories the repo.
- **The decisions log is written but not transmitted.** It is the agent's ungated
  self-report; passing it forward as fact contradicts the rule above. `notes-next.md` is the
  phase-to-phase channel.
- **The timeout is idle time, not a deadline**: a hung pi process stalls a whole night, a
  long productive phase must not be killed.
- **The agent reports through tools** (`styre-tools.js`) writing the same `.styre/` files;
  styre still runs the gate itself, and only that run decides.
- **The pi invocation is fixed**: no `--pi-cmd`, no `--model`. pi's own settings, in styre's
  config directory, pick the model.
- **One report per run**, `summary.md`, computed from the timeline.
- **Cross-platform**: pathlib, no POSIX-only shell syntax inside the package.

Parked, ask before adding: held-out tests, spend budgets, a placeholder scan, parallel
phases, run notifications, a queue of designs (the director chains runs).

## Keep it simple

The plainest thing that works. No knob with one sensible value, no abstraction with one
caller, no feature nobody asked for; prefer deleting code to adding a flag that guards it.
Stdlib only at runtime. When simplicity and a safety rule conflict, safety wins.

## Working on this code

- One module, one job; a new concern gets a module, not more `runner.py`.
- Tests: `uv run --with pytest python -m pytest -q`. The end-to-end tests drive the real loop
  against `tests/fake_pi.py`; add a case for anything new. Extension tests need `node`.
- Lint: `uvx ruff check .`. Python 3.9+:
  `uv run --isolated --python 3.9 --with pytest python -m pytest -q`.
- pi is available — get real data from it, and capture new fixtures into `tests/fixtures/`.
- A release: bump `__version__`, suite and ruff green, `uv build`, `uvx twine check dist/*`,
  the wheel holds `styre/pi_extensions/*.js` (`unzip -l dist/*.whl`), `uvx twine upload dist/*`.

## Safety

pi has no sandbox and runs commands without asking. Run in an ordinary clone of the target
repo, with only the credentials the job needs. On a timeout the whole process group is
killed, so tool children do not hold ports and locks into the next phase.
