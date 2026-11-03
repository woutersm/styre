# Design: M4, the advisor

Today any stop ends the run, and the person reads it in the morning. In the person's own
runs since styre 0.17, 9 stops came from the builder's work: 7 phases too big for one
context, 1 BLOCKED on a design defect and 1 phase with no diff. M4 hands each of those to
the **advisor**, Claude through `claude -p`, which answers with one action. A stop caused by
the model host still ends the run.

Terms used in every phase:

- **Phase**: one `## Phase N: Title` section of the design, built by the builder and
  committed as one commit. Do not call it a task or a step.
- **Gate**: the commands in a phase's `### Gate` block, which styre runs itself before it
  commits. Do not call them checks.
- **Builder**: the local model, through pi. **Advisor**: Claude, through `claude -p`, called
  when a phase stalls.
- **Stall**: a stop caused by the builder's work. The five kinds: the gate still red after
  the fix rounds, a relay that is stuck or past `MAX_RELAYS`, a state file that is missing,
  says BLOCKED or lists unmet criteria, and a green gate with no staged diff.
- **Host failure**: pi exiting non-zero, the idle timeout (rc 124), or an empty response.
  A host failure ends the run as today. The advisor is never called for one.
- **Advice**: the advisor's answer to one stall: an action, a reason and a text.
- **Actions**: `amend` adds text to the phase's prompt and runs the phase again. `split`
  replaces the phase, in this run only, with 2 or 3 smaller phases. `patch` has the advisor
  edit the code itself, then styre gates and commits it. `stop` ends the run with the
  advisor's reason.

Rules for the whole milestone:

| Topic | Decision |
| --- | --- |
| Calls | at most one advice per design phase; a split's new phases share their parent's. A second stall of the same phase stops the run |
| Patches | at most `MAX_PATCHES = 2` per run. Past that, `patch` is not offered |
| The design file | never edited or committed by styre. Advice lives in the run directory only |
| The tree | a stalled attempt's uncommitted work stays in the tree for the next attempt |
| Commits | a phase commit that holds a patch has the trailer `Styre-Advisor: patch`. No commit line names Claude, Anthropic or Claude Code |
| Runtime | stdlib only, Python 3.9+ (`from __future__ import annotations` at the top of each module), pathlib, no POSIX-only shell syntax in `styre/` |
| Modules | one module, one job: the advisor's call and its checks get `styre/advisor.py`, not more `runner.py` |
| Tests | pytest in `tests/`. The end-to-end tests drive the real loop against `tests/fake_pi.py` and `tests/fake_claude.py`. No test calls a real model |
| Comments | short and plain; say why, not what. A new module starts with a docstring saying its one job |
| Errors | one English sentence each, like `design.validate()`'s |

---

## Phase 1: The advisor's call and its checks

Add `styre/advisor.py`: the advice schema, the advisor prompt, one `claude -p` call with
one retry, and the checks on its answer. Nothing calls it yet; the runner uses it in
Phase 2.

The module's interface:

```python
ACTIONS = ("amend", "split", "patch", "stop")
MAX_PATCHES = 2
READ_TOOLS = ["Read", "Grep", "Glob"]

@dataclass
class Stall:
    n: str             # the phase number, as text: "3"
    phase: Phase       # styre.design.Phase
    context: str       # the phase's design excerpt, exactly as its builder prompt has it
    reason: str        # styre's sentence for why the phase stopped
    progress: str      # the builder's progress file, or ""
    gate_report: str   # the last gate failure report, or ""
    diff_stat: str     # `git diff --cached --stat` of the uncommitted work, or ""
    log: str           # path of the phase's readable log, relative to the repo root

@dataclass
class Advice:
    action: str        # one of ACTIONS
    reason: str        # one paragraph for the person
    text: str          # amend: text for the builder; split: the new phase sections;
                       # patch: the diagnosis for the patch call; stop: may be ""
    phases: list       # split only: the new phases, parsed; else []

def schema(actions) -> dict
def split_problems(phase, n, text) -> list[str]
def check(answer, stall, actions) -> tuple[Advice | None, list[str]]
def advise(stall, actions, *, cwd, timeline, log_dir) -> tuple[Advice | None, str | None]
```

- `schema(actions)` returns a JSON schema object: `{"type": "object", "properties":
  {"action": {"type": "string", "enum": list(actions)}, "reason": {"type": "string"},
  "text": {"type": "string"}}, "required": ["action", "reason", "text"],
  "additionalProperties": false}`. `actions` is a sequence of names from `ACTIONS`; the
  enum holds exactly those, in the order given.
- `check(answer, stall, actions)` judges the call's `structured_output`. It returns
  `(Advice, [])` when the answer is good, else `(None, problems)`, one sentence each:
  - `answer` is not a dict, or `action` is not in `actions`:
    `The advice's action must be one of: amend, stop.` (the names joined by `, `).
  - `reason` is missing or blank: `The advice has no reason.`
  - `text` is blank and the action is `amend`, `split` or `patch`:
    `The advice's text is empty; amend, split and patch need it.`
  - action `split`: every sentence `split_problems(stall.phase, stall.n, text)` returns.
- `split_problems(phase, n, text)` parses `text` with `styre.design.parse_phases`. It returns
  one sentence per broken rule, empty when the split is good:
  - 2 or 3 phases: `The split has 1 phase; it must have 2 or 3.`
  - phase k's title starts with `Phase {n}.{k}:`:
    `Split phase 2's title must start with 'Phase 3.2:'.`
  - every sentence `styre.design.validate(phases)` returns, unchanged.
  - the last phase keeps the stalled phase's gate, exit criteria and acceptance tests
    exactly: `The split's last phase must keep the phase's gate unchanged.`, and the same
    sentence with `exit criteria` and `acceptance tests`.
  - no earlier phase has acceptance tests:
    `Split phase 1 has acceptance tests; only the last phase may, and only the original ones.`
- `advise(stall, actions, ...)` calls `claude.call("advisor", advisor_prompt(stall,
  actions), schema(actions), READ_TOOLS, cwd=cwd, timeline=timeline, log_dir=log_dir)`.
  A call error returns `(None, result.error)`. An answer `check()` refuses gets one retry:
  the same prompt, then a blank line, `Your advice was refused:` and the problems, one per
  line. A second refusal returns `(None, problems[0])`. A good answer returns
  `(advice, None)`. This is the planner's retry in `styre/cli.py:115-131`, the same shape.

Add `advisor_prompt(stall, actions)` to `styre/prompts.py`. It states, in this order:

1. The situation: a local model, through the pi coding agent, built one phase of a design
   unattended, and the phase stalled. Nobody is watching; the person reads the run later.
   The advisor reads the repository with Read, Grep and Glob, and edits nothing.
2. The stall: `stall.reason`, then the phase's design excerpt (`stall.context`) inside
   `<phase>` tags, the progress file inside `<progress>` tags (or `(none)`), the gate report
   inside `<gate_report>` tags (or `(none)`), the diff stat inside `<uncommitted>` tags (or
   `(nothing uncommitted)`), and the log's path with the note that its end is the most
   recent.
3. The offered actions, only those in `actions`, one line each on when to choose it:
   - `amend`: the builder lacked a fact, a file, a signature or a rule. `text` is what the
     builder reads before it starts again on the tree as it is now.
   - `split`: the phase is too big for one context. `text` holds 2 or 3 sections in the
     design format, titled `## Phase {n}.1: ...`, `## Phase {n}.2: ...`, each with its text,
     a `### Exit criteria` list and a `### Gate` block. The last one keeps the phase's gate,
     exit criteria and `### Acceptance tests` section unchanged. The earlier ones get their
     own gate, green on their own work, and no acceptance tests.
   - `patch`: one hard part the builder will not get right. `text` is the diagnosis: what is
     wrong and what to change. A second call makes the edit.
   - `stop`: the design is wrong, or the stall needs the person. `reason` says what the
     person has to decide.
4. The rules: the uncommitted work stays in the tree; the design file is not changed; the
   advisor answers once for this phase; `reason` is one paragraph for the person.

**Where**
- `styre/claude.py:50-147` `call(role, prompt, schema, tools, *, cwd, timeline, log_dir,
  timeout=None) -> ClaudeResult`. `ClaudeResult` has `output` (the `structured_output` dict
  or None), `error` (one sentence or None), `usage`, `seconds`. It writes the
  `model_call` timeline event itself.
- `styre/cli.py:100-131` the planner's call and its one retry; copy its shape.
- `styre/planner.py:1-68` a module of the same kind: a docstring, a schema constant and a
  checking function returning sentences.
- `styre/design.py:95-126` `Phase` (`title`, `body`, `criteria`, `gate`, `acceptance`) and
  `parse_phases(text)`. `styre/design.py:160-182` `validate(phases)`.
- `styre/prompts.py:74-124` `planner_prompt(brief, window)`: the style of a frontier
  prompt. Add `advisor_prompt` after it.
- `tests/test_plan.py:31-69` `run_plan()` and `call_stdins()`: how a test sets
  `STYRE_CONFIG`, `PATH`, `FAKE_CLAUDE_REPLY` (a file, or a directory of `1.json`, `2.json`)
  and `FAKE_CLAUDE_LOG`. `tests/test_claude.py` calls `claude.call` directly with a
  `Timeline` and a `log_dir`. `tests/fixtures/claude_read_tools.json` is a real reply
  whose `structured_output` a test can replace.
- New: `styre/advisor.py`, `tests/test_advisor.py`.

Do not change `styre/runner.py`, `styre/claude.py` or `styre/cli.py` in this phase.

### Exit criteria
- `styre/advisor.py` defines `ACTIONS`, `MAX_PATCHES`, `READ_TOOLS`, `Stall`, `Advice`, `schema`, `split_problems`, `check` and `advise` with the signatures above.
- `styre/prompts.py` defines `advisor_prompt(stall, actions)`, which names only the actions in `actions`.
- `tests/test_advisor.py` covers each sentence `check()` and `split_problems()` return, and `advise()`'s good answer, retry and failed call through `tests/fake_claude.py`.
- Nothing outside `styre/advisor.py`, `styre/prompts.py` and `tests/` is edited.

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 2: Stalls go to the advisor: amend and stop

Wire the advisor into the run. A stall calls `advisor.advise()` once, offering `amend` and
`stop`. `stop` ends the run with the advisor's reason. `amend` runs the phase again, on the
tree as it is, with the advice added to its prompt. A host failure ends the run as today.

`run_phase(ctx, n)` returns a `PhaseResult` instead of a string:

```python
@dataclass
class PhaseResult:
    reason: str | None   # None: committed
    stall: bool          # True for the five stall kinds, False for a host failure
    gate_report: str     # the last gate failure's full report, or ""
    rounds: int          # fix rounds used, counted over every attempt of the phase
    relays: int          # relays used, counted over every attempt of the phase
```

Classify in `run_phase` where each `why` is set (`styre/runner.py:293-399`). Host
failures, `stall=False`: the `rc != 0` branch (pi exited, timeout) and the empty-response
branch. Every other `why` is a stall.

Give `run_phase` two keyword arguments, `advice=None` and `after=None`. With `advice` (the
advice's text) and `after` (the stalled attempt's `PhaseResult`), it runs the **amended
attempt**:

- It does not call `clear_progress()`: the progress file is the next attempt's start.
- It writes `run.advice(n)` (new in `styre/rundir.py`: `phase{n}.advice.md`) with
  `advice_prompt(n, phase, advice, read_progress())`, new in `styre/prompts.py`: the
  advice inside `<advice>` tags, the progress file block from `_progress_block()`, and one
  sentence that the tree holds the stalled attempt's work. The first step's prompts are
  `[builder, advice_file]`, a fresh process, step name `advised`.
- `rounds` and `relays` start at `after.rounds` and `after.relays`, so fix-round and relay
  file names continue (`phase1.fix3.md` after `phase1.fix2.md`) and none is overwritten.
  The limits count the amended attempt's own: `--retries` more fix rounds, `MAX_RELAYS`
  more relays.

In `orchestrate` (`styre/runner.py:416-440`), for a stall of a phase not yet advised:

1. Build an `advisor.Stall`: `n=str(n)`, the phase, `ctx.context(n)`, the reason,
   `read_progress()`, `result.gate_report`, `diff_stat()` (new in `styre/gitops.py`:
   `stage_all()`, then `git diff --cached --stat`), and `run.log(n)` relative to the
   repository root.
2. Call `advise(stall, ["amend", "stop"], cwd=Path.cwd(), timeline=tl,
   log_dir=run.root / "logs")`.
3. Write the timeline event `advice` with `phase=n`, `action`, `reason`; for a failed call
   `action=None` and `error` the sentence.
4. Failed call: stop with `Stopped at phase {n}: {reason}. The advisor could not be asked:
   {error} Work is left uncommitted.`
5. `stop`: stop with `Stopped at phase {n}: {reason}. The advisor stopped it: {advice
   reason} Work is left uncommitted.`
6. `amend`: `run_phase(ctx, n, advice=advice.text, after=result)`. A stall of the amended
   attempt stops with `Stopped at phase {n}: {reason}, after the advisor's amend. Work is
   left uncommitted.` and no second call.

A host failure, and a stall when the advisor call is not reached, keep today's message.

`preflight()` (`styre/runner.py:138-196`) prints, when
`shutil.which(settings.load()["frontier"]["command"][0])` is None:
`[warn] Claude Code ('claude') is not on PATH: a stall will stop the run instead of going
to the advisor.` (with the command's name). A `settings.SettingsError` becomes a
`PreflightError` with its message.

`summarize`: a phase's `advice` events become `Phase.advice`, a list of `(action, reason)`
pairs (`styre/summarize.py:173-217`, folded in `read_timeline` at 249-288). A phase with
advice counts in `Phase.problems`. `where_to_look` (591-643) prints, per advice,
`- the advisor chose amend: <reason>`, or `- the advisor could not be asked: <error>`.

The test fixture must never reach a real `claude`. The `styre` fixture
(`tests/conftest.py:89-112`) puts the real `PATH` after the fakes. Make it request the
`fake_claude` fixture (same `bin` directory, so `PATH` already holds both fakes) and set
`STYRE_CONFIG` to a `styre.json` in `tmp_path` holding
`{"frontier": {"command": ["claude"], "timeout": 60}}`, and `FAKE_CLAUDE_LOG` to a file in
`tmp_path`. With no `FAKE_CLAUDE_REPLY`, the fake prints nothing, the call fails, and every
existing stall test stops with its old reason still in the message. Tests pass a reply with
`env_extra={"FAKE_CLAUDE_REPLY": ...}`. A reply is a JSON file shaped like
`tests/fixtures/claude_read_tools.json` with `structured_output` replaced by the advice.

**Where**
- `styre/runner.py:261-406` `run_phase`: the loop at 293-385 sets `why` at each stop;
  the commit at 387-399; `phase_end` at 401-405. `styre/runner.py:416-440` `orchestrate`.
- `styre/runner.py:198-210` `empty_response(events)`.
- `styre/rundir.py:38-86` `RunDir`; add `advice(n)` beside `fix(n, round_)` at 50.
- `styre/prompts.py:127-157` `_progress_block` and `fix_prompt`: copy their shape for
  `advice_prompt`.
- `styre/gitops.py:32-45` `stage_all`, `staged_diff`, `commit`.
- `styre/settings.py:28-59` `load()` and `SettingsError`.
- `styre/summarize.py:173-217` `Phase`, 249-288 `read_timeline`, 591-643 `where_to_look`.
- `tests/conftest.py:67-112` the `fake_claude` and `styre` fixtures.
- `tests/test_run_end_to_end.py:68-111` the stall tests (`bad_gate`, `blocked`, `lying`,
  `nochange`) and 601-616 the relay stalls (`grow`, `stuck`). The fake pi picks its action
  by the last attached prompt's file name, so `{"phase1.advice.md": "ok"}` scripts the
  amended attempt.

### Exit criteria
- `run_phase` returns a `PhaseResult`, and a host failure has `stall=False`.
- A stall calls the advisor once with the actions `amend` and `stop`, and the timeline holds one `advice` event for it.
- `stop` ends the run with the advisor's reason in the stop message.
- `amend` runs the phase again from `phaseN.advice.md`, without clearing the progress file, and commits it when its gate is green.
- A second stall of the same phase stops the run without a second advisor call.
- A failed advisor call stops the run with the original reason and the call's sentence.
- An end-to-end test covers each of the four bullets above, and every existing test still passes.
- `summary.md` names the advisor's action and reason under "Where to look".

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 3: Patch

Offer `patch` while the run has made fewer than `advisor.MAX_PATCHES` patches. On
`patch`, a second advisor call edits the code, styre restores the acceptance tests and runs
the gate, and green commits the phase with the trailer `Styre-Advisor: patch`. Red stops
the run.

Add to `styre/advisor.py`:

```python
PATCH_TOOLS = ["Read", "Grep", "Glob", "Edit", "Write", "Bash"]
PATCH_SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}},
                "required": ["summary"], "additionalProperties": False}

def patch(stall, advice, *, cwd, timeline, log_dir) -> str | None
```

`patch()` calls `claude.call("advisor", patch_prompt(stall, advice.text), PATCH_SCHEMA,
PATCH_TOOLS, cwd=cwd, timeline=timeline, log_dir=log_dir)` and returns `result.error`
(None on success). It is not retried: a failed call may already have edited the tree, and
the gate, not the answer, decides. `patch_prompt(stall, diagnosis)` in `styre/prompts.py`
states: the diagnosis inside `<diagnosis>` tags; the phase's design excerpt and gate
commands; edit the tree so the gate passes; run the gate commands with Bash to check; do not
edit, skip or delete tests (styre's test guard rejects it); do not edit the acceptance test
files (styre writes them back); do not commit, switch branches or touch `.styre/`; return a
`summary` of what was changed.

In `orchestrate`:

- Count patches per run. Offer `["amend", "patch", "stop"]` while the count is below
  `MAX_PATCHES`, else `["amend", "stop"]`.
- On `patch`: call `patch()`. A failed call stops with `Stopped at phase {n}: {reason}. The
  advisor's patch call failed: {error} Work is left uncommitted.` Otherwise
  `styre.acceptance.write(phase, Path.cwd())`, logging restored paths as an
  `acceptance_restored` event with `step="patch"`, then `verify(phase, run.log(n), ...,
  step="patch")`. Red stops with `Stopped at phase {n}: {reason}. The advisor's patch left
  the gate red: {short} Work is left uncommitted.` and no builder fix round. Green: stage,
  and with a staged diff commit `f"{phase.title}\n\nStyre-Advisor: patch"`; write the
  `commit` event with `patch=True` and a `phase_end` event with `status="committed"`.
- Move the commit block of `run_phase` (`styre/runner.py:387-399`) into one function both
  paths call, so the "no staged diff" rule and the `commit` event stay in one place.

`styre/gitops.py:44` `commit(message)` passes the message to `git commit -m`; a message
with a blank line and a trailer works unchanged. Check it in a test with
`git log -1 --format=%B`.

`summarize`: a `commit` event with `patch=True` sets `Phase.patched`. `where_to_look` prints
`- the advisor patched it: the commit carries Styre-Advisor: patch`, and the phase table's
status cell reads `committed (patch)`.

`tests/fake_claude.py` learns to edit: when `$FAKE_CLAUDE_REPLY` is a directory and
`<dir>/<k>.files/` exists for call k, it copies that tree into its working directory before
it replies. Update its docstring. A patch test then uses a reply directory with `1.json`
(the advice, action `patch`), `2.json` (the patch call's answer, `{"summary": "..."}`) and
`2.files/done.txt`.

**Where**
- `styre/advisor.py` from Phase 1: `advise`, `check`, `schema`.
- `styre/runner.py` `orchestrate` and the advice handling from Phase 2; `run_phase`'s commit
  block, near the end of the function.
- `styre/guard.py:46-94` `verify(phase, log, gate_timeout=None, allow_test_changes=False,
  timeline=None, phase_n=None, step=None)` returns None or `(short, full)`.
- `styre/acceptance.py:12-31` `write(phase, root) -> list[str]`, the paths it restored.
- `styre/summarize.py` `Phase`, `read_timeline`, `phase_table` (around 462-470),
  `where_to_look`.
- `tests/fake_claude.py:20-44` `main()`: the reply-directory branch at 28-35.
- `tests/test_run_end_to_end.py`: the advisor tests from Phase 2.

### Exit criteria
- `advisor.patch()` uses `PATCH_TOOLS`, and the decision call keeps `READ_TOOLS`.
- A green patch commits the phase with the subject `{phase.title}` and the trailer `Styre-Advisor: patch`, and nothing in the message names Claude.
- A red patch stops the run and commits nothing.
- After two patches in one run, the next advice offers only `amend` and `stop`.
- An end-to-end test covers each of the three bullets above.
- `summary.md` shows `committed (patch)` for a patched phase.

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 4: Split

Offer `split` too. On `split`, styre runs the advisor's 2 or 3 phases, the **parts**, in
place of the stalled phase, in this run only. Each part is built, gated and committed like a
phase, with its own commit titled with the part's title. The parts run as attempts of the
stalled phase's number `n`, reusing the amended attempt from Phase 2, so phase numbers stay
integers everywhere. The design file is not changed.

The offered actions become `["amend", "split", "patch", "stop"]`, without `patch` once
`MAX_PATCHES` is reached. `advisor.check()` already refuses a bad split with
`split_problems()`, so a part list that reaches the runner is valid: 2 or 3 phases titled
`Phase {n}.1: ...`, the last one with the stalled phase's gate, exit criteria and acceptance
tests.

Give `run_phase` a third keyword argument, `part=None`: a `(k, Phase)` pair. With `part`:

- The phase is the part's `Phase`. Its design excerpt is
  `phase_context(ctx.text, ctx.phases[:n - 1] + [part_phase] + ctx.phases[n:], n)`: the
  index shows the part's title in phase `n`'s place.
- The builder prompt file is `run.split(n, k)` (new in `styre/rundir.py`:
  `phase{n}.split{k}.md`), built with `build_prompt`.
- Notes: part 1 reads `run.notes(n - 1)`, as phase `n` did. Part `k > 1` reads
  `run.notes(n)`, the notes the part before it wrote. After the last part, phase `n + 1`
  reads `run.notes(n)` unchanged.
- Part 1 keeps the progress file, and its first step's prompts are
  `[split_file, advice_file]`, where the advice file is `advice_prompt(n, part_phase, text,
  read_progress())` with `text` one sentence: `The phase was split; you build part 1 of
  {count}, {title}. The parts after it build the rest.` Parts 2 and 3 call
  `clear_progress()` and start from `[split_file]` alone.
- The tools and the gate are the part's: `start_phase_tools(n, part_phase.gate, ...)`,
  `acceptance.write(part_phase, ...)` and `verify(part_phase, ...)`.
- `after` carries the counters from the attempt before, as for amend, so no fix-round or
  relay file is overwritten. The first step's name is `split {k}`.
- The commit is titled `part_phase.title`; `phase_end` has `title=part_phase.title`.

In `orchestrate`, on `split`:

1. Write the timeline event `advice` with `action="split"`, the reason, and `titles`, the
   parts' titles.
2. Delete from the tree each of the stalled phase's acceptance files that exists. The last
   part writes them back at its start; an earlier part's gate must not run them.
3. Run the parts in order with `run_phase(ctx, n, part=(k, part_phase), after=result)`,
   `result` being the attempt before. A stall of a part stops the run with
   `Stopped at phase {n} ({part title}): {reason}, after the advisor's split. Work is left
   uncommitted.` and no advisor call.

`summarize` needs no change for the phase row: it keeps phase `n`'s last `phase_end` and
last `commit`, and sums its time and tokens over the parts. `where_to_look` prints, for a
`split` advice, `- the advisor split it into: ` and the titles joined by `; `.

**Where**
- `styre/runner.py` `run_phase` (its first lines read the phase, `ctx.context(n)` and
  `run.notes(n - 1)`, then call `clear_progress()`, `acceptance.write` and
  `start_phase_tools`), `orchestrate`, and the advice handling from Phases 2 and 3.
- `styre/design.py:146-157` `preamble`, `phase_context(text, phases, n)`.
- `styre/rundir.py:38-86` `RunDir`, with `advice(n)` from Phase 2; 144-150
  `start_phase_tools`; 152-155 `clear_progress`.
- `styre/acceptance.py:12-31` `write(phase, root)`: the paths it writes are
  `phase.acceptance`'s.
- `styre/summarize.py` `where_to_look`, with the advice lines from Phase 2.
- `tests/test_run_end_to_end.py`: the advisor tests from Phases 2 and 3. The fake pi picks
  its action by the last attached prompt's name: `phase1.advice.md` for part 1's first step,
  `phase1.split2.md` for part 2's.

### Exit criteria
- A split answer runs its parts in order, with one commit each, titled with the part's title.
- Each part runs its own gate, and the last part's gate, exit criteria and acceptance tests are the stalled phase's.
- Part 2 reads part 1's notes, and the phase after the split reads the last part's notes.
- A stall of a part stops the run, names the part's title, and makes no second advisor call.
- `summary.md` lists the parts' titles under "Where to look".
- An end-to-end test covers a two-part split that commits, and one where a part stalls.

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 5: Docs

Describe the advisor where a reader of styre looks for how a run works. Docs only.

- `CLAUDE.md`: add `styre/advisor.py` to the Files table. In "What happens per phase", step
  7: a stall goes to the advisor; a host failure stops the run. Under "Decisions that are
  settled", the bullet "Until a role exists, its judgement is the director's": the advisor
  now decides what a stall needs; reviewing a run stays the director's until M5.
- `docs/architecture.md`: in the "One phase" flowchart (lines 64-89), the stall edges
  (relay stuck, BLOCKED or missing state, no diff, retries used up) lead to "the advisor:
  amend, split, patch or stop"; the host-failure edges (pi exited non-zero or went silent,
  empty response) still lead to stop. Add `advisor.py` to the module table (lines 49-63).
  Change line 39-41: the director no longer decides what every stop means.
- `skills/styre/DIRECTOR.md` rule 3: on a stop, read the advice first (`summary.md`, "Where
  to look"). "Stuck twice on the same work: the director writes that part itself" stays,
  for a phase the advisor stopped.
- `skills/styre/SKILL.md` step 3, "Stop": a stop after advice names the action and its
  reason; a patch commit carries `Styre-Advisor: patch`.
- `README.md` line 19: the advisor is built; the reviewer is not.
- `docs/lessons.md`: nothing; there is no new measured failure yet.

### Exit criteria
- Each file in the list above says what its bullet asks, and no other file is edited.
- No doc names Claude, Anthropic or Claude Code as the author of a commit.

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```
