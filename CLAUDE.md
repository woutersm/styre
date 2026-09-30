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
| `styre/config.py` | Constants (`PI`, `PI_CONFIG_DIR`, `CLAUDE`, `WORK`, `DECISIONS`, `AGENTS`, `EXCLUDES`) and the `RunOptions` bundle. |
| `styre/design.py` | Parsing a design into `Phase` objects; `preamble()` and `phase_context()`; `validate()` (errors) and `advisories()` / `doc_references()` (warnings); the `check` rendering. |
| `styre/review.py` | `find_references()` / `describe_review()`: the second half of `check`, and what `run` calls automatically before phase 1 and after every commit. For every backtick-quoted identifier a phase names, greps the target repo's test-shaped files for existing references — the mechanical half of catching a phase that collides with a frozen test fixture, before a run starts rather than after a timeout. A name with more than `MAX_HITS` hits is dropped as a local variable or a library, not a collision. |
| `styre/claude_review.py` | Claude's read-only review of a finished run — see "The supervising layer". `claude_review()` writes `<run>/claude-review.md`; `CLAUDE_REVIEW` is the verified read-only invocation. |
| `styre/touch.py` | Claude as the escape hatch — see "The supervising layer". `run_claude()`, `touch_prompt()`, `touch()`: one turn at a stuck phase. Invoked only by `runner.py`'s `_escalate()`, only when `--claude-touch` is passed. |
| `styre/prompts.py` | `build_prompt()`, `fix_prompt()` (a fresh fix round), `resumed_fix_prompt()` (a resumed one), `handoff_prompt()` (a stopped step writes its progress file) and `relay_prompt()` (a fresh start for context). |
| `styre/pi_extensions/` | The pi extensions every pi process gets with `--extension`: `cap-output.js`, `no-compaction.js`, `strip-thinking.js`, and `styre-tools.js` — the agent's `styre_gate`, `styre_progress` and `styre_finish` tools, which write the same `.styre/` files the orchestrator reads (it hands them the phase in `.styre/phase.json`). See "Context". Unit-tested in Node by `tests/test_pi_extensions.py`; `styre-tools.js` was also run in real pi 0.87.1 against a scripted model server (2026-09-30). |
| `styre/agents.py` | `AGENTS_BODY`, the block written into the target repo's `AGENTS.md`. |
| `styre/process.py` | `run()` for gates, `stream_pi()` for the agent (it also tracks the context and stops pi at a turn end past `relay_at`, returning `RELAY_RC`), `render_event()` / `elapsed()`, `_watch_idle()`, `kill_tree()`. |
| `styre/gitops.py` | Every git call, including `stage()` / `unstage_all()` (one path, and an emptied index, for the touch's separate design-fix commit) alongside `stage_all()`. |
| `styre/guard.py` | `verify()` — the gate — and `test_tampering()`. `TEST_PATH` is also what `review.py` scopes its grep to. |
| `styre/rundir.py` | The per-run directory `.styre/runs/<id>/`: its paths, `latest.txt`, and collecting the agent's two files into it. |
| `styre/state.py` | Reading and judging `phaseN.state.json`. |
| `styre/summarize.py` | Reading a finished run back off disk: the `summarize` subcommand, and the report every `run` prints as it ends. Calls no model. |
| `styre/watch.py` | `styre watch`: a read-only web view of this repo's runs on localhost. The run list reads only each timeline; a run page scans that run's events on demand; the live panel reads forward from a byte offset so a 2-second refresh is free. Writes nothing, serves nothing off this machine. |
| `styre/server.py` | The model server's `/status` for the live panel — `watch`'s one outbound read. Finds the server from styre's pi config (default provider's `baseUrl` and `apiKey`), caches the answer 5 s, and gives no line for a server without `/status` (mlxserve). |
| `styre/timeline.py` | `Timeline`: the append-and-flush writer behind `<run>/timeline.jsonl`. |
| `styre/runner.py` | `preflight()`, the `Ctx` bundle the loop is threaded with, the phase loop (`run_phase`, `orchestrate`), and `_escalate()` — the Claude-touch bounding. |
| `orchestrate.py` | Deprecated shim mapping the old single-command form onto the subcommands. |
| `pyproject.toml` | Packaging and the `styre` entry point; ruff and pytest config. No runtime dependencies. |
| `example-design.md` | Two-phase example design (a `wordfreq` CLI; uv, pytest, ruff) for testing. |
| `writing-designs.md` | How to shape a design *before* a run: sizing a phase by its work, cutting phases where each gate stays green, where the ripple goes, and reading a stop back into a design change. Every rule names the run that taught it. For the human writing the design — never named in a design, or `advisories()` flags it. |
| `TODO.md` | What is left, what is a known limitation, and what is parked. Rewritten 2026-09-23; the reasoning lives here, not there. |
| `tests/` | pytest suite. `fake_pi.py` and `fake_claude.py` are test doubles installed on `PATH` as `pi` and `claude`, so the whole loop — including `--claude-touch` — runs without a model. |
| `tests/fixtures/*.jsonl` | Real captured pi JSON output: a plain reply, a run with a bash tool call, a saved session file, and `pi_usage.jsonl` with real token counts. Write every parser against these, not against assumptions. |

The `styre` package is the source of truth for how things behave today.

## Where it runs

styre is a standalone tool. It is not the repo being built. It must be invoked
from the root of the *target* git repository — the project the design describes — because it
switches branches and commits there, and writes `AGENTS.md` and `.styre/` into the directory it
starts in. `run` and `check` refuse a subdirectory (`gitops.not_at_root()`). This directory is not itself a git repo.

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

That is the format. **`writing-designs.md` is the shape** — how big a phase may be, where to
cut one so its gate is green on its own work, and why the rename-everything phase goes last.
Read it before writing or splitting a design; the failures it describes are ones that only
show up hours into a night.

## What happens per phase

0. Before phase 1, write the styre block into the target repo's `AGENTS.md` (`AGENTS_BODY` /
   `write_agents_file()`). pi discovers that file on its own and loads it into every run, so
   the standing rules, the "what gets checked" explanation and the three-file contract live
   there rather than in each prompt. A pre-existing `AGENTS.md` keeps its own text; only the
   `<!-- styre:begin -->` … `<!-- styre:end -->` block is replaced.

   It also tells the agent what **not** to read: nothing under `.styre/`. Naming a directory
   to an agent is an invitation to explore it, and on 2026-09-22 a phase spent its first
   eight steps and 18 minutes reading the orchestrator's own `timeline.jsonl`, `touches.json`
   and `review.md` instead of writing code. Same failure as the design document that told
   every phase to "read `docs/agent-design.md` first" — see "Prompt size".
1. Write a prompt containing the design excerpt for this phase (`phase_context()`: the
   preamble, an index of the phase titles with this one marked, and this phase's section in
   full — not the other phases' bodies), the previous phase's `notes-next.md`, and this
   phase's criteria and gate. It points at AGENTS.md rather than restating the rules.
   `docs/decisions.md` is **not** in it — see "Prompt size".
2. Start a fresh pi process: `pi -p --mode json --session-dir <run>/sessions/phaseN --name
   "<run-id> phase N <step>" @<prompt-file> "Follow the instructions in the attached file."`
   — the constant `PI` plus the two per-step session flags, under `--timeout` (default 7200 s
   of **silence**, not of total runtime — see "Watching a run"). Output is read line by line.
   Each raw line is stamped with our own wall-clock time and appended to
   `<run>/logs/phaseN.events.jsonl`; the condensed non-thinking rendering goes to the terminal in
   grey and, as it happens, to `<run>/logs/phaseN.log`. Keep that split: the log is for reading
   (a few KB), the events file is for parsing (a few hundred KB per phase). Putting raw JSON in
   the log once made it 180 KB with the gate output buried at line 404.
3. If pi's last message comes back with an all-zero usage block, the phase stops with
   **"the model returned an empty response"** rather than with whatever the agent failed to
   write. A provider that refuses a request and an agent that ignores its contract look
   identical from here — pi ends the turn and exits 0 either way — and on 2026-09-22 that
   ambiguity cost two days: the model host was rejecting the prefill for memory
   (`predicted peak would exceed prefill safety cap 37.8GB`) while styre reported "no state
   file written". See `runner.empty_response()`.
4. The agent ends by writing three files: `docs/decisions.md` (append-only, committed),
   `.styre/notes-next.md` (overwritten, read only by the next phase), and
   `.styre/phaseN.state.json` (`status`, `reason`, `unmet_criteria`, `fix_rounds_self`).
   `DONE` together with a non-empty `unmet_criteria` is rejected as contradictory. Those two
   short paths are a drop box, not the archive: once pi stops, `rundir.collect()` moves them
   into the run directory as `phaseN.state.json` and `phaseN.notes-next.md`. The agent's
   contract stays a stable path it can be told about in a committed `AGENTS.md`, which cannot
   name a run id.
5. On `DONE`, the orchestrator runs each gate command itself (`--gate-timeout`, default 900 s),
   printing each one before it starts and its verdict and duration after.
6. It then runs a test-tampering guard over the staged diff: added skip/xfail markers, or a
   net removal of test functions, fail the phase. Disable with `--allow-test-changes`.
7. Any failure is fed back as a fix round, up to `--retries` (default 2): the whole gate's
   failures at once, the phase prompt and the agent's progress file with them — or, when the
   failed step ended small, into that step's own resumed session. See "Context".
8. All green → `git commit -m "<phase title>"`. A phase whose gate passes but which staged no
   diff is treated as a failure, not a success — no empty commits. Otherwise the run stops and
   leaves the work uncommitted; `--from-phase N` resumes.

## Usage

Installed with `uv tool install -e .` (or `pip install -e .`); without installing, use
`python -m styre` with the repository on `PYTHONPATH`.

Install editable while this code is changing. uv caches a built wheel per source path *and
version*, so a non-editable `--force` reuses a stale wheel when the version has not moved.
That cost one overnight run: on 2026-09-20 a run went out with the old prompt builder — 66 KB
prompts carrying all fifteen phases — while `styre --version` and `styre check` were both
green. **Verify an install by behaviour** (the size of `.styre/runs/<id>/phaseN.prompt.md`),
never by the command answering.

**So bump `__version__` in `styre/__init__.py` whenever behaviour changes.** It is the cache
key and the only thing that makes `--force` rebuild. `pyproject.toml` reads it from the
package, so there is one number. Every run records it in `run_start`.

```
styre check design.md                  # validate; print phases, gates and prompt sizes;
                                       #   warn about risky shapes; then find existing
                                       #   test-file references its prose names
styre run design.md                    # run every phase
styre run design.md --from-phase 2     # resume after a stop, in the latest run directory
styre run design.md --from-phase 2 --run-id 20260920-2330   # ... in a specific one
styre summarize                        # what happened in the last run
styre summarize 20260920-233014        # ... or a named one, by id or by path
styre watch                            # read-only web view on localhost, live
styre watch -t                         # the same live panel in the terminal
styre claude-review                    # Claude reviews the last run's commits, read-only
```

Other flags on `run`: `--quiet` (no live echo to the terminal; the log is still written
live), `--retries`, `--timeout`, `--gate-timeout`,
`--allow-test-changes`, `--branch` (default `overnight/<design-stem>`), `--allow-dirty`,
`--reset-branch`, `--run-id`, `--claude-touch` (see "The supervising layer" — off by
default, real automatic spend against the `claude` CLI when it is on), `--claude-review`
(the same layer, after the last phase: a read-only review, at most $5).

`orchestrate.py` still works, translating the old single-command form onto the subcommands
with a deprecation notice on stderr.

## Preflight

Before phase 1: the design must parse, `pi` must be on PATH, `AGENTS.md` is written or
refreshed, the working directory must be a git repo with a clean tree, and the run switches to `overnight/<design-name>`. An existing run
branch is checked out, never reset — resetting it would throw away phases an earlier run
committed. Re-running phase 1 over a branch that already holds phase commits warns;
`--reset-branch` is the explicit, destructive opt-in. Orchestrator artifacts and caches are
appended to the exclude file located via `git rev-parse --git-path info/exclude`.

## pi runs under styre's own config, not yours

Every pi process is launched with `PI_CODING_AGENT_DIR=~/.config/pi/styre`
(`config.PI_CONFIG_DIR`), and preflight refuses to start if that directory has no
`models.json`. Gate commands and git keep the inherited environment; only pi is redirected.

This was measured, not assumed. On 2026-09-23 the *starting* context of a phase was 13,109
tokens, and only 32% of it was styre's:

| | chars | ~tokens |
| --- | --- | --- |
| `pi-web-access` tool schemas (`web_search`, `fetch_content`, `source_check`, `get_search_content`) | 11,551 | 3,160 |
| the operator's global `AGENTS.md` (writing style, "reader has ADHD") | 10,888 | 2,980 |
| styre's phase prompt | 11,316 | 3,090 |
| styre's `AGENTS.md` | 4,007 | 1,100 |
| pi's own tools and rules | 8,500 | 2,320 |

Web-search schemas, in a run whose design says "no test touches the network"; prose-styling
rules, for output no human reads. A trivial prompt cost **8,331 tokens** of fixed overhead
under that config and **1,639** under a lean one — 80% off *every request of every turn*,
which is also KV that no longer has to fit on the model host.

There is a second reason, already recorded under "Where the model runs": `PI_CODING_AGENT_DIR`
is exported from `~/.zshrc`, so a run started from cron or launchd fell back to the dead
pre-16-September `~/.pi/agent` tree. Setting it explicitly closes that too.

Keep the directory lean — `models.json`, `auth.json`, a `settings.json` carrying nothing an
unattended run does not use, and **no `AGENTS.md`**. The repo's own `AGENTS.md` still reaches
the agent; it is a project file, found by pi in the working directory, not part of this config.

**Removed again on 2026-09-28: `packages` is empty.** app's phase 3 used only `read` and
`bash` while the web tools' schemas were 11,830 of 14,914 characters of tool definitions;
a trivial prompt went from 5,065 back to 1,588 tokens. The same run found the other two
context costs — whole-file reads (~67% of a 60k phase) and thinking replayed by modelhost
(~12%, see `extensions/strip-thinking.js` under "Where the model runs"). What follows is
the history of why it was added; put it back for a design that must read documentation.

**`pi-web-access` was in `packages`, deliberately, as the one exception** (added
2026-09-26 for app's TanStack design). The rule above said *no* packages because 3,160 tokens
of web-search schemas in a run whose design says "no test touches the network" is pure waste.
That reasoning holds and is not repealed; what changed is that a design arrived whose framework
the local model does not know and cannot be told in a prompt — so the documentation has to be
fetchable, and the four tools (`web_search`, `fetch_content`, `get_search_content`,
`source_check`) come as one package.

Measured on the same trivial prompt, before and after, under this config: **1,627 → 5,065
input tokens**, so it costs **+3,438 tokens of every request of every turn**. Against a ~40k
phase that is 8%, and it is KV that has to fit on the model host (see "The host runs out of
memory long before it runs out of context"). It is not free and it is not per-design: every
run under this config now pays it. If a design has no reason to reach the network, take the
package back out — and a design that does reach it must bound the fetching in its own prose,
because a fetched page lands in the phase's context and stays there.

`web-search.json` is copied in beside it with `autoOpenBrowser: false`: nothing unattended
should be able to open a browser. No search-provider key is configured, so `fetch_content` on
a known URL is the capability being bought here; search is whatever the package's keyless
fallbacks manage.

**`contextWindow` and `maxTokens` are set to what the host can do, not what the model
claims** (2026-09-25). The model advertises a 262,144-token window; this host refused a
prefill at `kv_len=129344`, so the config said twice the truth and nothing in the stack knew
there was a wall until it hit one. `contextWindow` is 120000. `maxTokens` was 32768 against
a measured maximum output of **8,249 tokens over 257 messages** (p99 7,607, p90 2,411), so
it is 12288 — 1.5x the worst case ever seen rather than 4x. ⚠️ This file said neither number
is a limit pi enforces. **Wrong**: pi compacts once context passes `contextWindow −
reserveTokens` (120000 − 16384), in print mode too — it did so 16 times in one phase on
2026-09-28. styre now cancels that compaction and manages context itself; `contextWindow` is
also what styre's relay and resume thresholds are fractions of. See "Context".

**The thinking budget is not the lever it looks like.** `thinkingBudgets.medium` is 8,192 and
only **1 of 259** thinking blocks in a measured run exceeded it; the median block is 339
characters. Thinking is outlier-dominated — ~40k of one phase's 54k output tokens — so
cutting the budget would buy real time, but it clips the hard steps, and there is no evidence
here that the cap is what is costing anything.

**`preserve_thinking: false` is now validated** (2026-09-25). It was set on 2026-09-23 at the
worst possible moment — six clean commits banked — and this file said to revert it if a phase
looped or `fix_rounds_self` jumped. Six further phases have committed since with
`fix_rounds_self` of 1, 2, 3, 1, 1 and no loop. The warning is closed.

`$STYRE_PI_CONFIG_DIR` overrides the path so the test suite can use a temporary directory.
It is not a user-facing knob and `run` has no flag for it.

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

### `styre watch`, when the terminal is not where you are

`styre watch -t` (`--terminal`) draws the same live panel in the terminal instead, redrawn
every 2 s: phase, elapsed, peak ctx against pi's window, ctx/min, tok/s, a block-character
sparkline, the server line and the last 12 log lines. It follows the latest run (`--run ID`
for another), `--once` prints it once. Both views render `live_facts()`, so they cannot
disagree about a number.

`styre watch` serves the same facts as a page on `http://127.0.0.1:8765/`, read-only, from
the run directories of the repo it is run in. It answers the one question the terminal does
not: *is the phase running now going to make it.*

Three reads with three different costs, which is the whole design:

| View | Reads | Costs |
| --- | --- | --- |
| the run list | `timeline.jsonl` only, ~4 KB a run | 3 ms on app's three runs |
| one run | that run's `logs/phaseN.events.jsonl`, on demand | 0.8 s over 41 MB |
| the live panel | forward from a byte offset (`_Tail`), appended bytes only | ~1 ms a poll, at 2 s intervals |

**tok/s is measured over model time, not wall time.** Each message's own `message_start` →
`message_end` span, summed, against the output tokens of those messages: tool calls and the
waits between messages are excluded. Measured that way it agrees with what the model host
reports for itself (8.58 against the server log's 8.4-8.9 on app's phase 5, 2026-09-25),
because the span covers prefill and decode together, which is how the server computes its
own figure too. The obvious alternative — output over the phase's wall clock — is a
different number and an unusable one: it reads **0.60 tok/s** on a phase whose events file
spans a failed attempt, a six-hour gap, and the resume that succeeded.

Across app's reminders run it makes the decay in CLAUDE.md's own throughput note visible
per phase: 48k ctx → 10.1 tok/s, 51k → 9.3, 72k → 8.6, 77k → 8.0, 86k → 7.6, 96k → 6.2.

**The live panel splits that rate in two** (2026-09-28), because the blended number hid
where the time went: it read 4.6 tok/s on modelhost while the model wrote at ~36 and prefilled
at ~116 — the M4's limit, the same on every server. `message_start` → first `message_update`
is **prefill** (rate: the message's uncached `input` over that span, plus the share of model
time it took); first update → `message_end` is **writing** (output over that span). A phase
that reads a lot shows a high prefill share, and the lever is then context, not the server.
The run page's per-phase `tok/s` column stays blended, so history stays comparable.

The live numbers are phase and step, elapsed, **peak context**, context per minute, **prefill** and **writing** tok/s, and
**seconds since the last output** — the last one because the idle watchdog does not fire
until `--timeout`, hours later, while a human wants to know at five minutes. Each phase gets
an inline-SVG sparkline of context over time; no chart library, no CDN, nothing fetched.

⚠️ **A missing `run_end` is not a heartbeat.** The run list's first version called every
run with an unclosed invocation "running", and app's `20260921-045131` holds **17
`run_start`s against 5 `run_end`s** — twelve invocations killed at the terminal — so every
dead run read as live. A kill and a run in progress write the timeline identically; what
separates them is whether anything in the directory has been written lately. So the states
are: **running**, **running, silent Nm** past 5 minutes, and **abandoned** once the run has
been quiet longer than `DEFAULT_TIMEOUT` — styre's own idle limit, since `run` would itself
have killed the phase and written an ending by then. The middle state is deliberately not
called dead: pi prints nothing between `tool_execution_start` and `tool_execution_end`, so
a phase inside a long test suite looks exactly like a stalled one from out here.

The sparkline's danger line is **calibrated from this repo's own history** — the lowest peak
context at which a phase here has ever stopped — not from a constant. 85k and 130,901 are
facts about one model host, and a monitor that hardcodes them is wrong on the next one. A
repo where nothing has died yet gets no line, which is the honest answer.

It is **read-only and bound to 127.0.0.1**, deliberately both: the pages carry phase
prompts, diffs and decisions, and a monitor that can break the run it watches is worse than
no monitor. There is no route that changes anything, so there is nothing to confirm and no
auth to get wrong.

**It makes one outbound read: the model server's `/status`** (`styre/server.py`, added
2026-09-28 when the server became modelhost). A quiet phase can be the model thinking, a
request queued behind memory, or a server that is not serving, and only the server can say
which. The live panel shows one line from it — ready, memory pressure, requests waiting
(and how many on memory, oldest wait), the server's maximum context — and **peak ctx reads
against pi's `contextWindow`** ("59,447 of 120,000"). The server is found from styre's pi
config, the answer is cached 5 s so the 2-second poll costs the host one small GET every
few seconds, a slow host costs the page at most 1.5 s, and mlxserve (no `/status`) gets no line.
Serving stays 127.0.0.1-only; what changed is only that it reads one thing off the LAN.
tok/s needs no server help: it is already measured from pi's events, over model time.

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
                       project rather than per run. WRITTEN by the agent, never read back
                       to one: it is for a human, later
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
| `run_start` | `run`, `styre`, `design`, `design_sha256`, `templates`, `pi_version`, `pi_config`, `branch`, `phases`, `from_phase`, `retries` |
| `pi_start` / `pi_end` | `phase`, `step` (`builder` or `fix N`), and on end `seconds`, `rc` |
| `gate_start` / `gate_end` | `command`, and on end `seconds`, `rc` |
| `guard_result` | `ok`, `problem` |
| `commit` | `phase`, `sha`, `subject` |
| `phase_end` | `phase`, `status` (`committed`/`stopped`), `reason`, `rounds`, `fix_rounds_self`, `unmet_criteria` |
| `claude_review_start` / `_end` | `base`, `head`, and on end `seconds`, `rc`, `ok`, `cost`, `verdict` |
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
the design and template hashes), the per-phase table, and "where to look". The table carries
each phase's **commit sha** — the rollback point, and the thing most worth having in the
morning — and its **cache hits**, which is how a prompt prefix that stopped being stable
becomes visible (measured: 403k of 453k tokens on a healthy phase were cache reads).

`run` prints it and writes `summary.md` as it ends, so the morning report and the evening
one are the same artifact in the same format. There is no second per-run report to drift
out of step with it: `report.md`, which `run` used to accumulate as it went, is gone.

Things worth keeping right:

- **`-` is not `0.0`.** A dash means nothing was measured; a zero means it was, and was
  quick. Same rule as `n/a` for thinking tokens — absent is not zero.
- **Peak context is a maximum, output is a sum**, and the total row's peak is the largest
  phase, never the sum of the phases. The cumulative-usage trap one level down
  (`message_update.usage`) is avoided by reading only `message_end`.
- ⚠️ **There was an `Input` column here and it was wrong.** It reported the *last* `input`
  value on the belief that pi reports input cumulatively. It does not: on this provider
  `input` is one step's **uncached prefill**, non-monotonic across every phase of a
  12-phase run, and `totalTokens = input + cacheRead + output` exactly. So the column said
  1,149 for a phase whose context reached 44,766. Replaced by `Peak ctx` on 2026-09-23 —
  see "Token accounting", and do not restore an input column without re-measuring first.
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
  agent." Collapsed from a two-touch ladder to one touch on 2026-09-22.) Since 2026-09-29
  Claude may also review a finished run, read-only, once: the operator's call, "quality
  control by a higher-order agent" being the piece the gate cannot supply. It judges and
  never acts — never per phase, never mid-run, never a commit.
- The agent's claim of success is never trusted; the gate is the arbiter.
- One commit per phase, no tags — the commit is the rollback point.
- Per-run timeout stays: a hung pi process is the failure that stalls a whole night. It is
  measured as idle time, not total runtime (changed 2026-09-22; the code had always been a
  deadline while this file described a watchdog, and the deadline killed productive phases).
- Fresh pi process per phase. State lives in files and git, not in context. Within a phase
  that now holds too (2026-09-28): a step that outgrows its context budget continues in a
  fresh process from the agent's progress file, never by summarising its own history.
- Handoff state is split by lifetime: decisions are permanent and committed, notes last one
  phase, the progress file lasts one phase's steps, status is machine-readable. Nothing
  inventories the repo — the agent reads the tree.
- The decisions log is **written but not transmitted** (2026-09-22). `docs/decisions.md`
  stays per project, append-only and committed; no phase prompt carries it. It was the one
  artifact styre forwarded to the next agent *as fact* without the gate ever seeing it,
  which contradicts the second bullet above. `.styre/notes-next.md` is the phase-to-phase
  channel. Storage and transmission are separate questions: this bullet is about
  transmission, the one above it about storage, and only the first has changed.
- The prompt's fixed cost is amortised across phases, so it is worth bytes: the honesty rules
  around `unmet_criteria` earn their space. Trim wording, never a rule.
- Standing rules belong in `AGENTS.md` (pi auto-loads it, fix rounds included); only
  phase-specific material belongs in the prompt.
- `styre watch` is read-only and localhost-only (2026-09-25). It writes nothing — not even
  a cache — and has no kill or resume route. Since 2026-09-28 it *reads* one thing off this
  machine, the model server's `/status` (decided by the operator; see "Watching a run"):
  still a GET, still no route that changes anything, still served on 127.0.0.1 only. A stop button wants auth and a confirm, and a
  resume button starts unattended spend from a stray click; neither is worth it to a person
  who has a terminal open. The history view scans on demand rather than caching, so styre
  gains no new artifact and the viewer stays a pure reader.
- The CLI is subcommands (`styre check`, `styre run`), installed as a console script. A new
  verb is a new subcommand, not a flag on `run` — but a verb that answers the same question
  as an existing one is not a new verb: `styre review` was folded into `check` on
  2026-09-22, since both only ever answered "is this design safe to start tonight".
- One report per run, `summary.md`, computed from the timeline by `summarize`. `run` prints
  it as it ends rather than accumulating a second one of its own.
- One directory per run; the agent's own two output paths stay short and stable, and the
  orchestrator archives them. A committed `AGENTS.md` cannot name a run id, and a long path
  is one more thing for the model to get wrong.
- The pi invocation is fixed: `pi -p --mode json`, the constant `PI`, plus per step
  `--session-dir` (or `--session <file>` for a resumed fix round), `--name`, one
  `--extension` per file in `styre/pi_extensions/`, and the prompt files. No `--pi-cmd`, no
  `--model`, no auto-appended `--no-approve`. Local models only; pi's own settings pick which — but from **styre's**
  pi config directory, not the operator's (2026-09-23, see "pi runs under styre's own
  config"). An unattended run inheriting an interactive setup is how 47% of a phase's
  context became web-search schemas and writing-style rules.
- Never commit on a red gate.
- Cross-platform: pathlib, no POSIX-only shell syntax inside the package. (The end-to-end
  tests' own fixture gate uses `test -f`, so they skip on Windows.)

Parked, ask before adding: hidden held-out tests, spend/time budgets, placeholder scan,
parallel phases, run notifications, a run-level circuit breaker on repeated Claude
escalations (considered 2026-09-21, not needed yet).

## pi reference (verified against 0.85.1 on 2026-09-19; running 0.87.0 since 2026-09-23)

Do not guess at pi's behaviour — run it and look. Samples are in `tests/fixtures/`.
Everything below still held on 0.87.0, with two additions noted inline.

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
  mlxserve model**. Cost reports as zero because nothing is billed; token counts are real — see
  "Token accounting". "Where the model runs": local does not mean same machine.
- `--thinking <level>` takes `off|minimal|low|medium|high|xhigh|max`. styre does not pass
  it; the level and its token budget live in pi's settings — see "Where the model runs" for
  why the budget is the knob that matters and how it reaches the server.
- **The system message is large and is not styre's.** Its `sections` (`preamble`, `tools`,
  `rules`, `docs`, `project_context`, `cwd`) plus `toolsAdded` came to 36,721 chars on a
  real phase — 2.7× everything styre sent. `project_context` inlines every `AGENTS.md` pi
  finds, including one in its own config directory. Read it out of a session file
  (`<run>/sessions/phaseN/*.jsonl`, row 5) when a prompt is unexpectedly large.

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

- pi issues **parallel tool calls**: two `message_update.toolcall_start` events can arrive
  before either executes. `render_event` assumes strict interleaving, so the live log
  concatenates their arguments and check-marks on one line. Cosmetic; the events file is
  correct.
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

## Context: how a phase's context is kept small (2026-09-28)

Measured the same day, on app through modelhost: prefill is **~108 tok/s whatever the server**
(the M4 Pro is the limit), tool output was **67% of a 60k context**, pi's `read`/`bash` return up
to **2,000 lines / 50 KB** per call, and pi's own compaction **failed 16 times in one phase**
because the summary request thought until the token cap — 53 minutes lost before it began
failing fast. Three rules follow, and every mechanism below is one of them:

1. **Keep tokens out at the source.** Every token that enters costs prefill and stays.
2. **Never rewrite history.** Changing an earlier message invalidates the prompt cache from
   that point; re-prefilling 80k is ~13 minutes. That rules out compaction and "forgetting"
   old tool results alike.
3. **When a step fills up, restart it from a file**, not from a summary: styre's own "state
   lives in files" applied within a phase.
   The file is written by the step itself, in a handoff turn before the restart: on app's
   phase 3 (2026-09-28) the builder reached 72k without ever writing it, and the first fresh
   start spent 80 minutes re-reading the same files and re-probing the same library.

| Mechanism | Where | What it does |
| --- | --- | --- |
| Output cap | `pi_extensions/cap-output.js` | a `read` returns at most 300 lines, a `bash` its first 60 and last 90, both at most 16k chars, with a note saying what was cut and how to get it. Applied in `tool_result`, so the capped text is what pi stores and the cache stays valid |
| No compaction | `pi_extensions/no-compaction.js` | cancels pi's compaction (`session_before_compact` → `cancel`). Verified against real pi: without it three failing summary requests, with it none, `compaction_end` `aborted` |
| No replayed thinking | `pi_extensions/strip-thinking.js` | drops earlier thinking from every request (modelhost ignores `preserve_thinking`) |
| Whole gate on failure | `guard.verify()` | every gate command runs even after one fails; the fix prompt gets all failures at once |
| Progress file | `AGENTS.md` block, `rundir.py` | the agent keeps `.styre/progress.md` (Done / Now / Next / Learned, under 40 lines) as it goes; cleared at phase start, archived as `phaseN.progress.md`, handed to every fix round and relay |
| Relay | `process.stream_pi(relay_at=…)`, `runner.run_phase` | a step whose context passes **0.75 × contextWindow** (90k; 0.6 until 2026-09-29 — on modelhost writing flattens at 26-27 tok/s from 40k to 80k, so a fresh start costs more than staying) is stopped at the next `turn_end`, gets one **handoff turn** in its own resumed session (still cached) that only writes the progress file — ended by styre at the first `turn_end` after the file changes (`done_when`), since one handoff kept coding for 42 tool calls — and continues in a fresh process with the task files and that file. Not a fix round. **Bounded by progress:** a fresh start that ends with the tree (`gitops.work_tree_id()`, a throwaway-index `write-tree`) and the progress file both unchanged stops the phase; `MAX_RELAYS` (6) is only the backstop. A step that had already written its state file when stopped is judged normally |
| Resumed fix round | `runner.run_phase` | when the failed step ended below **0.5 × contextWindow** (60k), the fix round continues its session (`--session`), still in the server's cache, with a short prompt. Above it, a fresh process gets the phase prompt, the failures and the progress file |
| Visibility | `summarize`, `watch` | relays, resumed rounds, cancelled and failed compactions are counted; a relay's `RELAY_RC` is never reported as pi failing |
| Phase shape | `design.toolchains()`, `new_dependencies()`, `check` | names, in one line, the phases gated in two toolchains (backend + UI: 6 of 7 peaked at 74-116k on app), flags a phase using a declared, not-yet-installed library with no code example, and prints this repo's history against the budget. Replaced the path-spread heuristic on 2026-09-29: measured against 44 phases it flagged 12, of which 6 ran large |

The fractions come from the model's `contextWindow` in styre's pi config, so they move with the
host; a config naming no default model switches relay and resume off. The fix prompt used to
carry only the failure text, and a fresh fix round began by grepping the design: a fresh fix
round now attaches the phase prompt first. `--from-phase` continues the latest run only when
it ran the same design — resuming into another design's run directory mixed two designs'
event files on 2026-09-28.

⚠️ `strip-thinking.js` also sits in `~/.config/pi/styre/extensions/` from before it moved
into the package; pi then loads it twice (harmless, it is idempotent). Delete that copy.

## Prompt size

Everything in a phase's context costs KV on the model host for the whole phase, so the rule
is one line: **a phase prompt carries what that phase needs and nothing else.** Three things
were found violating it, each measured on `app` in September 2026.

| what was in the prompt | why it went |
| --- | --- |
| `docs/decisions.md`, 29.6 KB | ungated agent self-report, forwarded to the next agent as fact |
| a preamble line, *"read `docs/agent-design.md` first"* | turned a 2.3 KB phase into a 44 KB context |
| pi's own packages and global `AGENTS.md`, 22.4 KB | see "pi runs under styre's own config" |

Phase 3's whole context went **22,500 → 4,200 tokens**, and the phase that had failed three
times committed on the first try.

**The decisions log is written but not transmitted.** Reading the one section that survived
scoping settled it: four of its seven bullets restated what the tree already showed, one was
status the gate had proved, and none was about the phase that would read it. Every other
thing the agent says is checked — by the gate, by the staged diff, by the state-file rules —
and this was the only unchecked thing passed forward. `.styre/notes-next.md` does that job
better: addressed to one phase, written forward, 900 bytes against 2,564, consumed rather
than compounding. The risk accepted is that notes last one hop, so a Phase 1 decision that
Phase 9 needs will not survive; the answer then is to put it in the design, by hand.

### Tool results are the biggest thing in a phase, and `read` is most of them

Measured over four phases of app's reminders run (2026-09-25), by share of the characters a
phase generated or received:

| | phase 3 | phase 5 | phase 6 | phase 7 |
| --- | --- | --- | --- | --- |
| tool results | 32% | 38% | 45% | 42% |
| assistant text | 23% | 33% | 32% | 30% |
| thinking | 30% | 23% | 13% | 16% |
| tool call args | 15% | 7% | 9% | 12% |

The single largest tool result of the whole run was the agent **reading `docs/decisions.md`
— 51,589 chars, ~13,943 tokens in one call.** That is the file this document decided on
2026-09-22 to stop transmitting; it came back through the side door, because `AGENTS.md`
tells the agent to *write* it and the agent opened it first. It is 50 KB because every phase
since has appended, so the cost grows with the project. `AGENTS.md` now says to **append to
it without reading it** — it is append-only and nothing in it is addressed to the agent.

Second: `src/app/store.py` was read whole in four separate phases at 5.2-5.8k tokens each.
`AGENTS.md` now tells the agent to **read narrowly** — grep for the lines, read a range, and
read a file end to end only when about to rewrite it end to end. The rule is framed to the
agent as its own throughput, because that is what it is: the same phase decodes at 10 tok/s
early and 6 tok/s late.

These two rules cost ~1.1 KB in a block that ships to every phase (now 5,830 chars ≈ 1,576
tokens) against ~14,000 tokens saved in one call in one phase. That trade is only worth
making for something this size — the block is not the place for advice.

**A phase that points at a file has an unbounded prompt.** Write phases that are
self-contained. When a reference document is organised per module — as a good one is — fold
each module's section into its phase and stop shipping the document.

`styre check` now says this before a night is spent rather than after. `advisories()` flags
a document the prose tells the agent to **read** — a named document is fine, designs
cross-reference plans constantly, and a design that says *"do not open `docs/`"* must not be
warned about its own fix, so a negation before the verb flips the meaning. It also flags a
phase much larger than its neighbours or carrying more than 8 exit criteria, and a phase
whose prose **asks for a skipped test** — the guard rejects an added skip or xfail marker,
so such a phase fails verification for doing what the design told it to (app phase 12,
2026-09-23: *"skip on non-macOS as `tests/test_scripts.py` already does"*, agent complied,
guard rejected, a fix round spent arguing the markers back out). Only the directive forms
count: a marker name, `skip` governing a test noun, or `skip on/when/unless`. The loose
version flagged *"`rrule`'s skipping behaviour"* — the subject under test — which is the
same signal-in-noise failure again. All three are advice and never change the exit code. Without the reading-verb and negation rules the check
reported 7 documents on a real design where 1 mattered — the same signal-in-noise failure
`review.py` made with `MAX_HITS`.

What stays, deliberately:

- The design block is an **excerpt**: preamble, a phase-title index, that phase's section.
  On the 63 KB `gateway-todo.md` that is ~65 KB → 16–20 KB per prompt. The cost is that
  **the preamble ships to every phase**, so keep it to what every phase needs.
- Each phase's criteria and gate appear twice, in the `<design>` block and in the focused
  section below it (~0.7 KB). That states the contract plainly instead of making the agent
  find its own phase.
- Standing rules live in `AGENTS.md`. This moves ~3.4 KB rather than removing it — pi loads
  that file anyway — and buys one source of truth plus fix rounds that carry the full
  contract.

## Working on this code

- Python stdlib only at runtime. pytest is the one dev dependency; nothing else.
- Keep every existing behavior working.
- One module, one job. A new concern gets a module; it does not get bolted onto `runner.py`.
- `TODO.md` holds the agreed next steps; start there.
- pi is available and authenticated — get real data from it rather than assuming. Capture new
  fixtures into `tests/fixtures/` when a task needs a shape not covered there.
- Run the suite: `uv run --with pytest python -m pytest -q`. The end-to-end tests drive the
  real phase loop against `tests/fake_pi.py`, so a behavior change shows up there. Add a case
  for anything new rather than only testing it by hand.

## Token accounting

Usage lives at `message_end.message.usage`. To total a phase, read
`<run>/logs/phaseN.events.jsonl` and, over the `message_end` events, **sum `output` and take
the largest `totalTokens`** — `message_update.usage` is cumulative within a step and must
never be summed. The first `message_end` of a run carries `None` rather than `0`; absent is
not zero.

⚠️ **`input` is not cumulative.** This file said it was until 2026-09-23, and `summarize`
had an `Input` column built on it. Measured over all twelve phases of the app run: `input`
is non-monotonic in every one, and `totalTokens = input + cacheRead + output` holds exactly
(44,766 = 1,149 + 43,008 + 609). It is the step's **uncached prefill**, so the last value is
one step's tail and the sum is total prefill work. Neither is a phase's context; that is
`max(totalTokens)`.

**Peak context is what a phase costs.** Across those twelve phases wall time ran at roughly
**a minute per 1,000 tokens of peak context** — 22.9k/17.6 min, 44.8k/37.9, 59.1k/61.8,
60.4k/69.0, 66.2k/78.9, 86.3k/94.0 — with the rate sagging from 1,300 tok/min at 23k to 920
at 86k as decode halves from 23 to 12 tok/s. The two phases over 85k were the slowest and
the one that timed out. Size phases against this number, not against the prompt.

**Smaller context is faster, measured per phase.** Decode rate against peak context over
one 7-phase run (2026-09-25), from `styre watch`'s tok/s:

| peak ctx | 48k | 51k | 72k | 77k | 86k | 96k |
| --- | --- | --- | --- | --- | --- | --- |
| tok/s | 10.1 | 9.3 | 8.6 | 8.0 | 7.6 | 6.2 |

Doubling context costs about 39% of the rate: decode is memory-bandwidth-bound, and every
token re-reads the whole KV cache. **The curve flattens below ~30k**, though: a second run
the next day ran phases at 14k/19k/28k and measured 10.7/9.2/10.7 tok/s — no better than
48k's 10.1, and not even monotonic, because down there the rate is set by per-turn prefill
and MTP acceptance rather than by KV size. So 96k → 48k is worth 4 tok/s and 48k → 14k is
worth half of one: size phases under ~60k and stop there. It compounds, because a bigger phase generates more
tokens *and* generates each one slower — phase 6 at 96k took 130 minutes for 37k output
tokens, phase 3 at 48k did 22k in 56. This is the second dataset saying the same thing as
the twelve-phase run above, and it is the measurement behind `writing-designs.md`.

`totalTokens` includes `cacheRead`, and **prompt caching is live** — on a measured phase,
403k of 453k tokens the model saw were cache hits on the stable prefix. A collapse in that
ratio means a prompt prefix stopped being stable.

Two traps this file has already fallen into:

- ⚠️ **Usage was zero for a configuration reason, not a local-model reason.** The mlxserve
  provider declared `compat: {supportsUsageInStreaming: false}`, so pi streamed without
  asking for usage. It is `true` now. `pi_simple.jsonl`, `pi_toolcall.jsonl` and
  `pi_session.jsonl` predate the fix and read as zeros; `pi_usage.jsonl` is the one with
  real numbers. A parser written against the older three must not conclude counts are
  always zero.
- ⚠️ **`usage.reasoning` is not trustworthy on mlxserve.** It reported `0` on a message carrying
  a 66,781-character thinking block (2026-09-23). The `n/a is not 0` rule still holds for
  providers that omit the field, but here a reported `0` means nothing. `summarize.
  thinking_tokens()` therefore disbelieves a zero beside thinking blocks and splits the
  message's output by characters instead. modelhost's own figure agreed with that split within
  4 points on three phases (2026-09-29), so on modelhost the Thinking column is a measurement,
  and it reads 68-82% of all output. `watch` shows the same share live.

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
`.zshrc`, it reaches interactive shells only. styre no longer depends on any of that: it
exports `PI_CODING_AGENT_DIR` itself — see "pi runs under styre's own config". The model is
pinned in that config's `settings.json` (`defaultProvider` + `defaultModel`). Before
2026-09-28 nothing pinned it, and with a single mlxserve model listed pi simply took that one.
Still read `model` out of the event stream rather than assuming.

**Since 2026-09-28 the server is modelhost, not mlxserve**: provider `modelhost`, model
`mlx-community/Qwen3.8-27B-4bit`, medium, on the same host and port (8000; mlxserve is stopped
— both will not fit, and they share the port). The provider block is the one modelhost's own
`modelhost pi` writes (`install/clients.py`): `openai-completions`, `thinkingLevelMap
{"off": "none"}`, `maxTokens` 32768; `contextWindow` is styre's 120000, not the 262144 the
server advertises. The mlxserve models stay listed in `models.json`, so going back is a
settings change. Serve it with `modelhost serve --model mlx-community/Qwen3.8-27B-4bit --host
0.0.0.0 --api-key <key> --max-cache-disk 16G`.

Why, measured with `~/Dev/model-bench` on 2026-09-27/28:

- **Decode 2-3x mlxserve's on the same size of model** (oQ4e): 56 vs 28 tok/s at 2k, 42 vs 14
  at 64k, 31 vs 10.6 at 96k. The gap grows with context.
- **Prefill is not faster on this M4 Pro** (127-130 at 2k, 96-106 at 64-96k, both servers).
  modelhost's 3x prefill claim is M5 hardware; the chip is the limit here. So inside styre,
  where each step waits a median ~6 s for its first token, a phase is ~1.5x faster, not 3x.
- The prompt cache works across pi's steps (366k cached against 22.7k new prefill over a
  26-step phase), and a styre phase committed first try with a perfect hidden-oracle score.

⚠️ **modelhost has no thinking budget.** Effort names go to the template, "not token budgets"
(its DEVELOPMENT.md), and every budget field is silently ignored. On a large one-shot
module it thought 74-122k characters and failed 4 of 4 ways (cut at the cap, stopped with
an empty answer, one syntax error in 924 lines). `maxTokens` 32768 is the only backstop;
the gate and fix rounds catch the damage. A phase that produces one very large file is
where this bites. Upstream #123: `low`/`xhigh` collapse to medium on this model.

⚠️ **A turn can end `stop` with no text** (seen once, mid-thought at 25k tokens). styre
reads that as an agent that broke its contract, not as the server — the 2026-09-22
ambiguity again, with non-zero usage so `empty_response()` does not catch it.

⚠️ **modelhost #184** (open): tool-call arguments containing an array or object are buffered
until complete and the stream carries only SSE comments meanwhile. pi's `write`, `edit`
and `bash` take strings and stream normally; a structured-argument tool goes silent.

Before modelhost: `Qwen3.8-27B-oQ4e-mtp` on mlxserve (2026-09-28 morning), chosen over oQ6e for
no memory wall — at 64k oQ4e prefilled at 103 tok/s unthrottled against oQ6e's 39, and at
96k mlxserve refused oQ6e outright. xhigh made neither 27B better and cost 4x the time.

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

### The host runs out of memory long before it runs out of context

The model advertises a 262K context window. It cannot hold one. Measured 2026-09-23:

```
iogpu.wired_limit_mb ceiling  42.0 GB      soft 37.8 GB (90%)   hard 39.9 GB (95%)
model weights, pinned         23.2 GB      → ~14.6 GB for KV + prefill transient
```

Three failure shapes come out of that, and they look nothing alike from styre:

1. **Rejection.** `Chunked prefill capacity rejected … predicted peak would exceed prefill
   safety cap`. The server returns an **empty stream**; pi ends the turn and exits 0; the
   agent writes none of its files. `runner.empty_response()` exists so styre says "the model
   returned an empty response" instead of blaming the agent — that ambiguity cost two days.
2. **Thrash.** `Memory pressure ok → soft → hard`, reclaim ~11 GB, back to ok, repeat every
   ~11 s. Forward progress stops while pi keeps printing, so **the idle watchdog never
   fires**. It is the one hang shape that keeps talking.
3. **Throttle.** `Prefill throttled: chunk 2048 -> 1568`. Benign; the scheduler coping.

The transient scales with prefill chunk size (`per_token × chunk ≈ predicted`), not with
KV format, so KV quantization and chunk size are independent levers. What actually fixed it,
in order of effect: cutting context (see "Prompt size" and the pi-config section), capping
the model's thinking budget, and TurboQuant 8-bit KV — which converts only **15 of 64 cache
layers**, so it is worth roughly a quarter of what "8-bit" suggests.

After those, a phase ran to **54,969 tokens** of context and committed, against rejections at
19,968 and 26,080 before. Raising `iogpu.wired_limit_mb` and dropping KV to 6-bit were both
sized against the remaining ~0.5 GB gap and turned out not to be needed.

**The thinking budget is the knob that matters most**, and it is not styre's: it lives in
pi's `settings.json` as `thinkingBudgets`, and reaches an OpenAI-compatible server only if
the provider's `compat` block names the field (`thinkingTokenBudgetField: "thinking_budget"`
here — off by default, so the budget silently goes nowhere without it). A hardcoded
`reasoning_effort: "xhigh"` in `chatTemplateKwargs` outranked pi's own level until it was
bound to `{"$var": "thinking.effort"}`. With a budget of 8,192, peak thinking fell from
66,781 characters to ~12,700.

### Where a long phase's context actually comes from

Not the prompt. Measured on a 12-phase design's hardest phase (2026-09-23), which ran from
7,304 to 86,334 tokens: **the phase prompt was 4.5% of it.** The rest is the work.

| source | chars | ~tokens |
| --- | --- | --- |
| tool results (`read` 22 calls, avg 5,989 ch; largest 17,115) | 198,203 | 53,568 |
| assistant text — the code it writes | 164,534 | 44,469 |
| thinking | 78,530 | 21,224 |
| tool call args — the code again, going out | 52,969 | 14,316 |

Those overlap — a file is written as tool-call arguments, echoed in the edit result, and
sometimes re-read — so they sum to more than the growth; the ranking is what holds. The
lesson is that once prompts are lean, **the only lever left on context is how much work a
phase does**, which is the argument for splitting a phase rather than making room for it.

### `preserve_thinking` is model-specific, not an optimisation

`chatTemplateKwargs.preserve_thinking` decides whether the model's own reasoning is replayed
in later turns. There is no universal right answer:

- **Qwen3 strips prior-turn thinking by convention.** Its chat template drops `<think>`
  blocks from historical assistant messages and the model is trained that way, so `false`
  matches the model and `true` is the unusual setting.
- **Anthropic's extended thinking is the opposite within a turn** — thinking blocks must be
  passed back through a tool-use cycle or signature verification fails, though they are
  dropped across user turns.

Set it from the model's own documentation, not from the token arithmetic. The open question
on mlxserve is granularity: Qwen's convention strips *prior user turns*, but an agent loop is one
user message spawning forty assistant/tool cycles, and a flag that also strips the thinking
attached to the tool call just issued would be more aggressive than Qwen intends.

⚠️ It was set to `false` for styre runs on 2026-09-23 **with six consecutive first-try phase
commits already banked and nothing failing**, which is the wrong time to move a variable. If
a later phase loops, forgets, or shows a jump in `fix_rounds_self`, that is the first thing
to revert. Test a change like this at the start of a run, not at phase 10 of 12.

## Safety

pi has no sandbox and runs commands without asking. Run overnight jobs in an ordinary clone
of the target repo (not a linked worktree), with only the credentials the job needs, and set
a spending limit with the model provider. The orchestrator limits time per run but does not
track spend.

On a per-run timeout the whole process group is killed, not just pi, so tool children do not
survive to hold ports and locks into the next phase.

## The supervising layer — Claude as the escape hatch (built 2026-09-21, simplified 2026-09-22)

Decided after a real run: a phase hit a genuine contradiction between the design and a
pre-existing test fixture and burned 3h40m before the timeout killed it, rather than the
agent ever reporting `BLOCKED`. Claude, reading the logs afterward, diagnosed it in minutes
and patched the design by hand. This makes that deliberate rather than accidental, inside
`styre run` rather than an external script.

`styre/touch.py` holds the one Claude invocation (`touch()`); the bounding (`_escalate()`)
lives in `runner.py`, beside the rest of the phase loop it extends. `--claude-touch` on `run` turns it on — off by
default, because it is real, automatic spend against the `claude` CLI, and every existing
test (and every run before today) had no reason to expect that. Every phase stop still
behaves exactly as before when the flag is not passed.

**The invocation, verified 2026-09-21, not guessed:** `claude -p --output-format json
--dangerously-skip-permissions "<prompt>"` (the `CLAUDE` constant in `config.py`, the same
shape as `PI`). `--output-format json` gives one parseable object —
`{result, is_error, total_cost_usd, session_id, ...}` — no new parsing needed.
`--permission-mode acceptEdits` **denies Bash outright** (confirmed live), so
`--dangerously-skip-permissions` is the only flag that works unattended. Anthropic's help
text for it says *"Recommended only for sandboxes with no internet access"*, which this is
not. Accepted on purpose, after being told so explicitly — the same risk `pi`'s own lack of
a sandbox already carries (see "Safety").

Three tiers, each trusting the one below only as far as the gate can verify it:

- pi (the local model) is styre's tool for writing a phase.
- styre is Claude's tool for running a gated phase loop.
- Claude, invoked only at a phase boundary, sits above styre and uses it as its tool.

**The gate does not care who wrote the diff.** This is what makes the arrangement safe:
"the agent's claim of success is never trusted, the gate is the arbiter" holds exactly as
written whether "the agent" is a local pi process or Claude itself. Verification never
changes; only who gets a turn at writing the phase does.

**Never mid-phase.** styre reads the design once at phase start, so there is nothing useful
to do while pi works. The only sound entry point is where styre already stops on its own:
`BLOCKED`, a timeout, or the gate still red after `--retries`.

**One touch per stuck phase, zero on a clean one.** In a single turn Claude:

1. Patches the design if it is wrong — an instruction contradicting the repo, a real
   ambiguity, a missing pointer. `ctx.reload()` re-reads it, so every later phase gets the
   fix too.
2. Implements the phase. `verify()` — the same one pi's diff is held to — decides. On green,
   `commit()` runs with an `Escalated:` line in the body, so the history records that this
   phase was not written by the local model.
3. If the touch cannot get the gate green, stop and tell a human. A gate that resists both
   the local model's retries and Claude is not a capability gap to push through further; it
   needs a person.

**Why one call and not two.** The original ladder was a review touch and an execute touch
with a `touches.json` counter. Collapsed 2026-09-22: the split was a cost optimisation, not
a safety property — `verify()` judges both paths identically — and it cost a counter file, a
"design bug or capability gap?" classification, a re-entrant call into `run_phase()`, and a
third outcome to reason about at 3am.

**Bounding:** a phase has had its touch if the timeline holds a `touch_start` for it. No
bookkeeping file; a resumed run appends to the same timeline it reads, so a resume cannot
spend a second touch (`test_a_second_stop_on_the_same_phase_does_not_touch_again`). The
design fix is committed on its own (`Touch: design fix for phase N`) against an emptied
index, so a phase that stopped on the test guard cannot ride along with it: a plan change
and a code change are different kinds of change.

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

**The review: once per run, after the last phase, read-only** (`styre/claude_review.py`,
`run --claude-review` or `styre claude-review [run]`, 2026-09-29). The gate proves the code
agrees with the tests the local model wrote itself; the EditTodo bug of 2026-09-27 shipped
behind such a gate and was found only by reading the code. One `claude -p` reads the design,
`summary.md` and `git diff <first phase commit>^..<last>`, and answers with a verdict (MERGE /
FIX FIRST / REDO), up to 15 ranked findings with `path:line`, and what the next design should
say. It is written to `<run>/claude-review.md`; `summarize` puts the verdict at the top of
"Where to look". The invocation is `CLAUDE_REVIEW`: `--tools Read,Grep,Glob,Bash`,
`--allowedTools` limited to those and `git log/diff/show`, no `--dangerously-skip-permissions`,
`--max-budget-usd 5`, a 30-minute cap. **Verified live**: a `touch` through Bash came back in
`permission_denials` and no file appeared. Nothing is fixed, committed or re-run on its
account, and a failed review never fails the run: merging stays a human's decision.

**Deliberately not built:** a run-level circuit breaker — see "Decisions that are settled"
and the parked list.

This reopens one settled decision, "no reviewer agent," on purpose, with reasoning, not by
drifting past it. "Decisions that are settled" above reflects the replacement.
