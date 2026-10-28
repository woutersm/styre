# Design: M2 — a Claude Code runner and `styre plan`

styre gets its first frontier role. `styre plan docs/<name>-design.md` takes a **brief** — a
v1 design with its phases, exit criteria, gates and interfaces, but without the
implementation help — and asks Claude, through `claude -p`, to add that help: per phase the
files and line ranges it touches, the signatures it calls, a working snippet for any library
new to the repository, the test to copy from, and the traps. styre checks that the answer
kept every line of the brief, writes it over the brief, and commits it for the person to
read. `styre run` is unchanged: it runs the planned design as it runs any v1 design.

| Topic | Decision |
| --- | --- |
| Runtime | stdlib only, Python 3.9+, pathlib, no POSIX-only shell syntax in `styre/` |
| Tests | pytest in `tests/`. No test calls a real model: `tests/fake_claude.py` stands in for `claude`, installed on `PATH` the way `tests/conftest.py` installs `fake_pi.py` (lines 56-64) |
| Real output | `tests/fixtures/claude_read_tools.json`, `claude_no_tools.json` and `claude_error_budget.json` are captured `claude -p --output-format json` results. Parse against them, not assumptions |
| The planner | reads only (`--tools Read,Grep,Glob`) and returns the whole design as text; styre writes it |
| Errors | a failed role call is one English sentence in the timeline and on stderr; styre never prints a traceback for one |

What one `claude -p --output-format json` run prints on stdout, when it succeeds (exit 0):

```json
{"type": "result", "subtype": "success", "is_error": false, "num_turns": 3,
 "structured_output": {"function": "add", "line": 1},
 "total_cost_usd": 0.161, "duration_ms": 6125,
 "usage": {"input_tokens": 4, "cache_creation_input_tokens": 19268,
           "cache_read_input_tokens": 5017, "output_tokens": 301,
           "output_tokens_details": {"thinking_tokens": 63}},
 "modelUsage": {"claude-opus-5-5": {"inputTokens": 4, "outputTokens": 301, "costUSD": 0.161}}}
```

and when it fails (exit 1): `"is_error": true`, a `subtype` starting `error_` (for example
`error_max_budget_usd`), `"structured_output": null` and `"errors": ["Reached maximum budget
($0.0001)"]`.

---

## Phase 1: `styre.json` and the Claude Code runner

A new module `styre/claude.py` runs one role call; a new module `styre/settings.py` reads
`styre.json`.

**`styre.json`** lives at `~/.config/styre/styre.json`, or at `$STYRE_CONFIG` when set. It is
optional; a missing file means the defaults. Shape and defaults:

```json
{"frontier": {"command": ["claude"], "timeout": 1800}}
```

`settings.load()` returns `{"frontier": {"command": [...], "timeout": int}}` with every
default filled in. A file that is not JSON, or a `command` that is not a non-empty list of
strings, raises `SettingsError` with one sentence naming the file.

**`claude.call(role, prompt, schema, tools, *, cwd, timeline, log_dir, timeout=None)`**
returns a `ClaudeResult` dataclass: `output` (the `structured_output` dict, or None),
`error` (one sentence, or None), `usage` (`tokens_in`, `cached_in`, `cache_write`,
`tokens_out`, `thinking`, `cost_usd`, `turns`), `seconds`.

- The command is `frontier.command` plus `-p --output-format json --json-schema <schema as
  JSON> --tools <tools joined by ",">  --no-session-persistence --permission-mode dontAsk`;
  with `tools` empty, `--tools ""`. The prompt goes in on **stdin**, never as an argument (a
  long argument breaks on Windows).
- Process rules as for pi (`styre/process.py`): its own process group (`_NEW_GROUP`, line
  33), `kill_tree` (line 37) after `timeout` seconds of runtime (default
  `frontier.timeout`). A `claude -p` call prints nothing until it ends, so here the timeout
  is a deadline.
- stdout goes to `log_dir/<role>.<n>.json` and stderr to `log_dir/<role>.<n>.err`, `n`
  counting that role's calls from 1.
- `error` is set when: the command is not found; the process timed out; the exit code is not
  0; stdout is not JSON; `is_error` is true (the sentence quotes `errors[0]` or the
  `subtype`); or `structured_output` is null.
- `tokens_in` is `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`,
  `cached_in` is `cache_read_input_tokens`, `thinking` is
  `output_tokens_details.thinking_tokens`; a missing field counts 0.
- Every call writes one `model_call` timeline event: `role`, `model` (the first key of
  `modelUsage`, or None), the usage fields, `seconds`, `ok` and `error`.

**`tests/fake_claude.py`**, installed on `PATH` as `claude` by a new `fake_claude` fixture in
`tests/conftest.py`: reads stdin, then prints the JSON object `$FAKE_CLAUDE_REPLY` names (a
file path), exits with `$FAKE_CLAUDE_EXIT` (default 0), and appends its argv and stdin as one
JSON line to `$FAKE_CLAUDE_LOG`. `$FAKE_CLAUDE_SLEEP` seconds before replying, for the timeout
test. When `$FAKE_CLAUDE_REPLY` names a directory, the call numbered *k* (counted through the
lines already in `$FAKE_CLAUDE_LOG`) prints `<dir>/<k>.json`, so a test can give a first and a
second answer.

### Exit criteria
- Each of the three fixtures, replayed through `fake_claude`, gives the documented `ClaudeResult`: the success with `output == {"function": "add", "line": 1}` and `tokens_in == 24289`, the budget error with `error` quoting `Reached maximum budget`
- A timeout, a missing command, a non-JSON stdout and a null `structured_output` each give an `error` sentence and a `model_call` event with `ok: false`
- The prompt reaches `fake_claude` on stdin and appears in no argv
- `settings.load()` covers: no file, `$STYRE_CONFIG`, bad JSON, a bad `command`
- No file outside `styre/claude.py`, `styre/settings.py`, `tests/` and `docs/decisions.md` changes

### Gate
```
uvx ruff check .
uv run --with pytest python -m pytest -q
uv run --isolated --python 3.9 --with pytest python -m pytest -q
```

---

## Phase 2: `styre plan`

A new module `styre/planner.py`, the planner prompt in `styre/prompts.py`, and a `plan`
subcommand in `styre/cli.py` beside `check` (line 153).

`styre plan <design.md>` from the repository root:

1. Refuses, as `run` does, a subdirectory (`gitops.not_at_root`, `styre/gitops.py` line 17)
   and a dirty tree (`gitops.is_dirty`, line 28). Reads the brief with `load_design`
   (`styre/cli.py` line 30) and refuses a brief `validate` (`styre/design.py` line 130)
   finds problems in. Calls `gitops.add_excludes()` (line 65), opens a run directory with
   `rundir.new_run()` (`styre/rundir.py` line 95), and writes `run_start` with
   `"kind": "plan"` and the design path to its timeline.
2. Calls `claude.call("planner", planner_prompt(brief, context_window()), PLAN_SCHEMA, ["Read", "Grep",
   "Glob"], cwd=<repo root>, timeline=..., log_dir=<run>/logs)`. `PLAN_SCHEMA` is
   `{"type": "object", "properties": {"design": {"type": "string"}}, "required": ["design"],
   "additionalProperties": false}`.
3. Checks the answer with `planner.problems(brief, planned)`, which returns a list of
   sentences, empty when the planned design is good:
   - `validate` on the planned design finds nothing;
   - the same number of phases, with the same titles in the same order;
   - each phase's gate is the same list of commands, and its exit criteria the same list;
   - **additive only**: every non-blank line of the brief's preamble appears, stripped, as a
     line of the planned preamble, and every non-blank line of the brief's phase *n* as a line
     of the planned phase *n* (`preamble`, line 116; `Phase.body`). A missing line is named:
     "Phase 2 dropped the brief's line: `<line>`.";
   - no advisory the brief did not already have: `advisories(planned) − advisories(brief)`
     (`styre/design.py` line 231), compared as strings, each one a problem;
   - no phase's prompt over 40,000 characters, measured as `phase_context(planned, phases,
     n)` (line 122).
4. Problems go back to the planner once, in a second call whose prompt is the first plus "Your
   design was refused:" and the problems, one per line. Still problems, or a failed call: the
   command prints the sentences, writes `run_end` with `stopped` set to the first one, leaves
   the brief untouched and the tree clean, and exits 1.
5. No problems: writes the planned design over the brief, stages it and commits it as
   `Plan: <design file stem>` on the current branch (`gitops.stage_all`, `gitops.commit`),
   writes `run_end` with `stopped: null`, prints the design path, the advisories it still has
   (the brief's own) and the planner's tokens in and out, and exits 0. The person reads the
   change with `git show` and runs `styre run <design.md>` when they agree.

**`planner_prompt(brief, window)`** in `styre/prompts.py` returns this text, with the brief at the end. `window` is `context_window()` (`styre/config.py` line 89); when it is None the sentence leaves out the context size:

> You are preparing a design for an unattended build. A local model, through the pi coding
> agent, with read, bash, edit and write tools, no web access and a context of {window:,}
> tokens, will build it one phase at a time. Each phase runs in a fresh process that sees only
> the design's preamble, the list of phase titles and its own phase section, nothing from the
> phases before it except the code they committed. Nobody watches, and it cannot ask questions.
> Everything it has to look up costs it context and time, so write down what you can find out
> now.
>
> The design below is a brief. Return the whole design with implementation help added. Keep
> every line of the brief exactly as it is, the phases, their titles, exit criteria and gates
> unchanged; add lines, never edit or remove them. Read the repository (Read, Grep, Glob) to
> find what you add. Add only what is true of the repository as it is now.
>
> For each phase, add under its text:
> - a **Where** list: each file the phase edits or must read, with a line range and one line on
>   what is there now, and the one existing test file it should copy from;
> - the exact signatures, types and constants it calls or changes, copied from the source;
> - for every library the repository has not used before: the imports, the calls in the order
>   the phase makes them and what each returns, in 15 lines or fewer, read from the installed
>   package source (for example under `.venv/` or `node_modules/`), with the traps;
> - the repository's conventions the gate depends on: test helpers and fixtures, how the
>   tests are run, lint rules that bite;
> - what the phase must not touch.
>
> Do not write the phase's own code: a snippet shows a library's calls, never the change the
> phase makes. Put what every phase needs in the preamble and everything else in the one phase
> that needs it. Do not tell the builder to read a document. Return the design in the
> `design` field.

Docs, in this phase: `README.md` gains `styre plan` in its command table and a short section
on what it does and what it commits; `CLAUDE.md`'s **Files** table gets `styre/claude.py`,
`styre/settings.py`, `styre/planner.py` and `tests/fake_claude.py`, and its `styre/cli.py` row
names `plan`.

### Exit criteria
- With `fake_claude` answering a good planned design: one commit `Plan: <stem>` changing only the design file, which now holds the planned text; one `model_call` event; the tree clean; exit 0
- A first answer that drops a brief line, changes a gate, or adds an advisory gets one retry whose stdin holds the matching problem sentence; a second bad answer exits 1 with the brief unchanged, no commit and a clean tree
- The planner error fixture (`claude_error_budget.json`) exits 1 with its sentence, no traceback, and `run_end` with `stopped` set
- `planner.problems` names each rule in step 3 when broken, one test per rule, and returns `[]` for a planned design that only adds lines
- A dirty tree or a subdirectory is refused before any call
- `styre run` is unchanged: every existing test passes

### Gate
```
uvx ruff check .
uv run --with pytest python -m pytest -q
uv run --isolated --python 3.9 --with pytest python -m pytest -q
```

---

## Phase 3: Model calls in the report, and `bench.py --plan`

**`styre summarize`** gets a `## Model calls` section after `## Model time`
(`model_time_table`, `styre/summarize.py` line 498), when the run's timeline has `model_call`
events: one row per role with calls, failed calls, tokens in, cached in, tokens out,
thinking, cost and minutes, and a total row. A run without such events has no section. The
run directory of a `styre plan` run (a timeline with `run_start` `kind: "plan"` and no phases)
summarizes without an error: its header, no phase tables, its `## Model calls`.

**`evals/bench.py --plan`**: after `do_setup` and before `do_run` (`run_bench`, lines
365-371), runs `<styre> plan <design_path>` in the copy, under the same cap clock, logging to
`plan.log` in the result directory. A non-zero exit sets `result["error"]` to "styre plan
failed: " and the last line of its output, and the design is not run. The result gains
`"planned": true|false`, `"plan_hours"`, and `"frontier"`: the sums of the plan run's
`model_call` events (`calls`, `tokens_in`, `tokens_out`, `cost_usd`), or null without
`--plan`. `hours` stays the `styre run` time.

**`evals/bench_report.py`**: `config_key` (line 60) includes `planned`, and `config_name`
adds "planned" after the variant when it is true. A group with any planned result gets two
more columns, `Plan h` and `Frontier tok` (tokens in plus out), summed in the total row.

`evals/README.md`: one paragraph on `--plan`.

### Exit criteria
- A run with two planner calls, one failed, shows both in `## Model calls` with the summed tokens; a run with none has no section; a plan-only run summarizes without an error
- `bench.py --plan` against a fake design with `fake_claude` and `fake_pi`: `plan.log` exists, `planned` true, `frontier.calls` 1, and the run used the planned design; a failing plan records the error and skips the run
- A report over planned and unplanned results of one setup shows two groups, the planned one with `Plan h` and `Frontier tok`
- No file outside `styre/summarize.py`, `evals/`, `tests/` and `docs/decisions.md` changes

### Gate
```
uvx ruff check .
uv run --with pytest python -m pytest -q
uv run --isolated --python 3.9 --with pytest python -m pytest -q
```
