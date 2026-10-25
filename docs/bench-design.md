# Design: a benchmark for styre itself

styre is about to change a lot, and every change has to show that it helps. This design adds
what that takes: `summarize` reports how much of each phase's time went to prefill versus decode and
how well the prompt cache held, `summarize --compare` puts two runs side by side, and two eval
scripts run a benchmark design end to end and report the results. **What `styre run` does
does not change**: no phase touches `styre/runner.py`, `styre/process.py`, `styre/guard.py`,
the prompts or the pi extensions.

| Topic | Decision |
| --- | --- |
| Dependencies | stdlib only, in the package and in `evals/` |
| Python | 3.9 and up: `from __future__ import annotations` at the top of every module, no `match`, no `X \| Y` outside annotations |
| Tests | pytest, in `tests/`. No test touches the network or calls a model; the fake agent `tests/fake_pi.py` stands in for pi, installed on `PATH` by the `fake_pi` fixture in `tests/conftest.py` |
| Style | ruff, line length 110; one job per function; a docstring on each new function says what it returns |
| Event files | `logs/phaseN.events.jsonl` has one line per pi event: `{"ts": <ISO time styre received it>, "line": <pi's raw JSON line>}` |

A **request** is one call to the model: an assistant `message_start`, the `message_update`
events it streams, and a `message_end` that carries a `usage` block such as
`{"input": 5378, "output": 229, "cacheRead": 6784, "totalTokens": 12391}`. `input` is the
prompt tokens the host had to process (not cached), `cacheRead` the prompt tokens it took from
its cache.

---

## Phase 1: Prefill, decode and cache hits in `summarize`

Read each request's tokens and timing out of the events file, and show them per phase.

1. **Stamped events.** Add `read_stamped_events(path)`, yielding `(ts, event)` where `ts` is
   the wrapper's `ts` parsed with `parse_ts` (None when missing or bad). `read_events` becomes
   a thin wrapper that drops the stamp; change its docstring, which says nothing is timed off
   the event stream.
2. **Per-request timing.** In `read_phase_events`, read stamped events. Remember the stamp of
   the latest `message_start` whose `message.role` is `"assistant"`, and the stamp of the first
   `message_update` after it. At the next `message_end` with a usage block: **prefill** is
   first update − start, **decode** is end − first update, in seconds; both None when any of
   the three stamps is missing. Then forget both stamps.
3. **`Usage` gains** `requests: int = 0`, `input: int = 0` (summed), `prefill_seconds: float = 0.0`,
   `decode_seconds: float = 0.0` and `timed: int = 0` (requests with both timings). `add(usage,
   content=None, prefill=None, decode=None)`: every call counts one request; `input` is summed
   like `output`; the timings are added when both are given. A property `cache_hit` is
   `cache_read / (input + cache_read)`, or None when both are 0.
4. **A second table.** `render` gets a `## Model time` section after `## Phases`: columns `#`,
   `Phase`, `Requests`, `Uncached in`, `Cached in`, `Cache hit`, `Output`, `Prefill min`,
   `Decode min`, one row per phase and a total row (sums; the hit rate over the summed
   tokens). `Cache hit` reads like `96.6%`, or `-` when there were no prompt tokens. The minute
   columns use `minutes(seconds, measured)` with `measured` = `timed > 0`. The `Cached` column
   leaves the Phases table, and the Phases note's sentence about it moves under the new table,
   with one sentence saying prefill runs from a request's start to its first streamed event and
   decode from there to its end, both by styre's arrival stamps.

Where:
- `styre/summarize.py` 42-58 — `read_events`; 79-117 — `Usage`; 254-278 — `read_phase_events`;
  398-437 — `phase_table`; 490-493 — `render`
- `tests/test_summarize.py` 12-30 — `events_file()` wraps a fixture at a fixed number of seconds
  per line, `make_run()` builds a run directory; copy a test from 63-68

### Exit criteria
- `tests/fixtures/pi_toolcall.jsonl` through `make_run` (one second per line) gives, for phase 1:
  2 requests, `input` 126, `cache_read` 3584, `cache_hit` 3584/3710, prefill 2.0 s, decode 46.0 s,
  `timed` 2
- A request whose stamps are missing counts as a request but adds no time, and `timed` says so
- The rendered summary has the `## Model time` table with `96.6%`, and the Phases table has no
  `Cached` column
- Every existing test in `tests/test_summarize.py` passes unchanged
- Only `styre/summarize.py`, `tests/test_summarize.py` and `docs/decisions.md` are edited

### Gate
```
uvx ruff check .
uv run --with pytest python -m pytest -q
uv run --isolated --python 3.9 --with pytest python -m pytest -q
```

---

## Phase 2: `styre summarize --compare A B`

Two runs side by side, per phase, to judge a change to styre against the run before it.

- `summarize.compare(a, b)` takes two `Run`s (from `collect`) and returns markdown: a heading
  `# Compare <a.id> → <b.id>`, one line per run with its design and styre version (from its
  first `run_start`), then a table with columns `#`, `Phase`, `Status`, `Agent min`, `Peak ctx`,
  `Fresh starts`, `Fix`, `Gate runs`, `Cache hit`, `Prefill min`, `Decode min`.
- One row per phase number found in either run, in order. `Phase` is the title from B, else
  from A. Every other cell is `<A value> → <B value>`, with `-` for a side that has no such
  phase. `Fresh starts` is `len(relays)`, `Fix` is `rounds`, `Gate runs` is `len(agent_gates)`
  (the agent's `styre_gate` calls). Values are formatted as the summary formats them.
- A total row, the same way: sums, except `Peak ctx` (the larger peak) and `Cache hit`
  (over the summed tokens).
- The CLI: `summarize` gets `--compare A B` (`nargs=2`, `metavar=("A", "B")`). Each is
  resolved with `rundir.resolve`, so a run id or a run directory path both work. It prints the
  comparison and writes no file. An unknown run exits with `No such run: <name>.`; giving both a
  run and `--compare` exits with `Give either a run or --compare A B, not both.`

Where:
- `styre/summarize.py` — `collect` (~302), `minutes`, `count`, `table`; the Phase 1 helpers for
  the cache hit and the time columns
- `styre/cli.py` 117-124 — `cmd_summarize`; 170-173 — the `summarize` parser
- `styre/rundir.py` 121-129 — `resolve`
- `tests/test_cli.py` 70-72 — the summarize argument test; `tests/test_summarize.py` `TIMELINE`
  (~116) and `make_run` to build two runs
- `TODO.md` — the open item `styre summarize --compare runA runB`: remove it

### Exit criteria
- Two runs built with `make_run`, one with `TIMELINE` and one where phase 1 took 300 agent
  seconds, give a row starting `| 1 | Phase 1: One | committed → committed | 15.0 → 5.0 |`
- A phase present in only one run shows `-` on the other side
- `styre summarize --compare A B` prints the table and creates no `summary.md` in either run
- An unknown run, and a run given together with `--compare`, exit with the sentences above
- `TODO.md` no longer lists `--compare`
- Nothing outside `styre/summarize.py`, `styre/cli.py`, `tests/test_summarize.py`,
  `tests/test_cli.py`, `TODO.md` and `docs/decisions.md` is edited

### Gate
```
uvx ruff check .
uv run --with pytest python -m pytest -q
uv run --isolated --python 3.9 --with pytest python -m pytest -q
```

---

## Phase 3: Scoring a reference suite from junit XML

A benchmark design ships with a reference test suite the builder never sees. It runs once,
after the run, and writes junit XML. This phase scores those files. It is a new script,
`evals/bench.py`; Phase 4 adds the runner to it.

Two kinds of reference test. **New** tests check what the design asks for and all fail before
the run. **Keep** tests check what must not change and all pass before it; a keep test that
fails afterwards is a **regression**. A test is a keep test when its testcase's `classname`
matches `"*" + keep_glob` with `fnmatch.fnmatchcase`; the glob comes from the benchmark
(`test_keep_*` for pytest, `*.keep.test.*` for vitest). Every other test is a new test.

- `read_junit(path)` returns `[(id, passed), ...]` for every `<testcase>` in the file, in
  order: `id` is `"<classname>::<name>"`, `passed` is true when the testcase has no `failure`,
  `error` or `skipped` child. A missing or unparseable file gives `[]`.
- `score(cases, keep_glob, expected_new, expected_keep)` returns a dict:
  `{"new": [passed, total], "keep": [passed, total], "failing": [...], "regressions": [...],
  "missing": n}`. `total` is the larger of the expected count and the number seen, so a test
  that never ran (a part that crashed, a file that did not import) counts as failed.
  `failing` and `regressions` are the sorted ids of new and keep tests that did not pass.
  `missing` is how many expected tests were not seen at all, new and keep together.

The script starts like `evals/advisories.py`: a module docstring with a usage line, then
`sys.path.insert(0, <repo root>)` so it can import `styre`. Tests import it with
`sys.path.insert(0, str(ROOT / "evals"))` and `import bench`.

What the two test runners write, trimmed (use these in the tests):

```xml
<testsuites name="pytest tests"><testsuite name="pytest" tests="3">
<testcase classname="bench_reference.test_keep_a" name="test_p[blank-name]" time="0.000" />
<testcase classname="bench_reference.test_keep_a" name="test_err" time="0.000"><failure message="RuntimeError: boom">...</failure></testcase>
<testcase classname="bench_reference.test_ref_a" name="test_ok" time="0.000" />
</testsuite></testsuites>
```

```xml
<testsuites name="vitest tests" tests="3">
<testsuite name="test/bench_ref/x.ref.test.ts" tests="2">
<testcase classname="test/bench_ref/x.ref.test.ts" name="group &gt; passes" time="0.0007"></testcase>
<testcase classname="test/bench_ref/x.ref.test.ts" name="group &gt; fails" time="0.0029"><failure message="expected 1 to be 2" type="AssertionError">...</failure></testcase>
</testsuite>
<testsuite name="test/bench_ref/x.keep.test.ts" tests="1">
<testcase classname="test/bench_ref/x.keep.test.ts" name="kept" time="0.0007"></testcase>
</testsuite></testsuites>
```

Where:
- `evals/advisories.py` 1-30 — the docstring, `sys.path` and import pattern to copy
- `tests/test_summarize.py` 1-10 — the import style for a test file

### Exit criteria
- The pytest sample with `test_keep_*` scores `new [1, 1]`, `keep [1, 2]`, regression
  `bench_reference.test_keep_a::test_err`
- The vitest sample with `*.keep.test.*` scores `new [1, 2]`, `keep [1, 1]`, failing
  `test/bench_ref/x.ref.test.ts::group > fails`
- With `expected_new` 5 on the vitest sample: `new [1, 5]`, `missing` 3
- A missing file and a file that is not XML both read as `[]`
- Only `evals/bench.py`, a new `tests/test_bench.py` and `docs/decisions.md` are edited

### Gate
```
uvx ruff check .
uv run --with pytest python -m pytest -q
uv run --isolated --python 3.9 --with pytest python -m pytest -q
```

---

## Phase 4: Running one benchmark design

`python evals/bench.py <design-dir> [--variant brief|full] [--styre CMD] [--pi-config DIR]
[--label TEXT] [--out DIR]` runs one benchmark design from start to score. `--variant` defaults
to `brief`, `--styre` to `styre` (split with `shlex.split`, so `"python -m styre"` works), `--out`
to `<design-dir>/../results`.

The same design is run against different model hosts, quants, model versions and context
sizes, so each result records what it ran on. `--pi-config DIR` is the pi config directory
the run uses (default: `styre.config.PI_CONFIG_DIR`); the script passes it to styre as the
environment variable `STYRE_PI_CONFIG_DIR`. One directory per setup, each with its own
`settings.json` (`defaultProvider`, `defaultModel`, `defaultThinkingLevel`) and `models.json`:

```json
{"providers": {"splash": {"baseUrl": "http://m4:8000/v1",
  "models": [{"id": "mlx-community/Qwen3.8-27B-4bit", "contextWindow": 120000}]}}}
```

`--label` is free text for what the config cannot show, such as `splash 0.4, kv 8-bit`.

A design directory holds `bench.json`, the design files and the reference suite:

```json
{
  "repo": "~/Dev/heim",
  "start": "ddc18656e48714af3818564a23c35fb59203508e",
  "design_path": "docs/todo-rules-design.md",
  "phases": 5,
  "setup": ["uv sync --locked"],
  "reference": {
    "keep": "test_keep_*",
    "parts": [{"dir": "reference", "into": "bench_reference",
               "command": "uv run pytest -q bench_reference --junitxml={junit}"}]
  },
  "checked": {"start": {"commit": "ddc1865", "new": [0, 17], "keep": [9, 9]}},
  "designs": {"brief": "brief.md", "full": "design.md"}
}
```

Other keys may be present; ignore them. `run_bench(design_dir, variant, styre_cmd, out)` does,
in order:

1. **A result directory** `<out>/<design-dir name>-<variant>-<YYYYmmdd-HHMMSS>/`, holding
   `repo/`, `junit/`, `setup.log`, `styre.log` and `result.json`.
2. **A clean copy of the start tree, with no history.** `git clone --quiet <repo> repo`
   (`repo` with `~` expanded), `git checkout --quiet --detach <start>`, delete `repo/.git`
   (`shutil.rmtree`), then `git init --quiet -b main`, `git add -A`,
   `git commit --quiet -m "bench: start <start[:7]>"`. The builder must not be able to find the
   finished work in `git log`. Then append each pattern in `styre.config.EXCLUDES` to
   `repo/.git/info/exclude`, as styre's own preflight does, so setup's dependency folders do
   not dirty the tree.
3. **The design.** Copy `designs[variant]` over `design_path` in the copy; when `git status
   --porcelain` shows a change, commit it as `bench: <variant> design`.
4. **Setup.** Each `setup` command with `shell=True`, `cwd` the copy, output appended to
   `setup.log`. A non-zero exit, or a tree that is not clean afterwards, ends the run here with
   `error` set to one sentence naming the command or the dirty paths.
5. **The run.** `<styre_cmd> run <design_path>` in the copy, with `STYRE_PI_CONFIG_DIR` set to
   the pi config directory, stdout and stderr to `styre.log`, timed by the script. The version is the last word of `<styre_cmd> --version`.
6. **Reading the run.** The run id is in `repo/.styre/latest.txt`; read the run with
   `collect(RunDir(repo / ".styre" / "runs" / run_id))` from `styre.summarize` and
   `styre.rundir`. `committed` is the number of phases whose `status` is `"committed"`;
   `stopped` is the last `run_end`'s `stopped` (`Run.last`). `served` is
   `"<provider>/<model>"` from the first assistant `message_start` in the phase events
   (`read_events`) whose `message` has both keys: what pi actually called, which is null when
   no request was made.
7. **Only committed work is scored.** `git reset --quiet --hard` and `git clean -fdq` in the
   copy. `.styre/` and dependency folders survive: styre lists them in `.git/info/exclude`.
8. **The reference suite.** For each part: copy `<design-dir>/<dir>` to `<copy>/<into>`
   (`shutil.copytree`, `dirs_exist_ok=True`), run `command` with `{junit}` replaced by the
   absolute path `junit/part<i>.xml`, `shell=True`, `cwd` the copy, a 900-second timeout.
   Record each part's exit code and whether its junit file exists. Score all parts' cases
   together with Phase 3's `score`, expecting `checked.start.new[1]` new and
   `checked.start.keep[1]` keep tests.
9. **`result.json`**, written even when an earlier step failed:
   `design`, `variant`, `styre` (version), `label`, `model` (from the pi config directory:
   `{"provider", "id", "base_url", "context_window", "thinking"}`, each null when the config
   does not say), `served`, `start`, `started` (ISO), `hours` (the run step's
   wall time / 3600, rounded to 0.01), `exit_code`, `run_id`, `phases` (from `bench.json`),
   `committed`, `stopped`, `error`, the score's keys, `parts` (`[{"command", "rc", "junit"}]`),
   and `usage`: `requests`, `input`, `cache_read`, `output`, `peak`, `prefill_seconds`,
   `decode_seconds`, `agent_seconds`, `gate_seconds`, summed over phases (`peak` the largest).
   Keys a failed run never reached are `null`.

`main(argv=None)` parses the arguments, calls `run_bench`, prints one line such as
`todo-rules brief: new 15/17, keep 9/9, 3/5 phases committed, 1.20 h -> <result.json path>`,
and returns 0 when `error` is null, else 1.

**The test** drives the whole thing with real styre and the fake agent:
- the conftest `repo` fixture is the source repository (`README.md` and `design.md`, one
  commit); `fake_pi` gives a `PATH` with the fake `pi`; `pi_config` a pi config directory
- a design directory in `tmp_path` with `bench.json` (`design_path` `"design.md"`,
  `setup` `["true"]`, one part `{"dir": "reference", "into": "bench_reference", "command":
  "<sys.executable> -m pytest -q -p no:cacheprovider bench_reference --junitxml={junit}"}`,
  `checked.start` `new [0, 1]`, `keep [1, 1]`), a `brief.md` that is conftest's `DESIGN` with
  each gate changed to `test ! -e bench_reference && test -f done.txt` (so a reference suite
  in the tree during the run fails the gate), `reference/test_ref_done.py` asserting
  `Path("done.txt").exists()` and `reference/test_keep_readme.py` asserting
  `Path("README.md").exists()`
- `monkeypatch.setenv` for `PATH` (the `fake_pi` value), `STYRE_PI_CONFIG_DIR`,
  `PYTHONPATH` (the repo root), `FAKE_PI_DEFAULT`, and `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`,
  `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL`: CI has no git identity
- `--styre "<sys.executable> -m styre"`, `--pi-config` the `pi_config` directory with a
  `settings.json` naming `defaultProvider` `local` and `defaultModel` `m`, and a `models.json`
  with that provider (`baseUrl` `http://localhost:1/v1`) and model (`contextWindow` 1000)

Where:
- `tests/conftest.py` 12-37 — `DESIGN`; 40-52 — `repo`; 55-64 — `fake_pi`; 67-74 — `pi_config`;
  77-101 — how `styre` is called with that environment
- `tests/fake_pi.py` 138-175 — the actions: `ok` writes `work<n>.py` and `done.txt`,
  `blocked` writes a BLOCKED state and no work
- `styre/summarize.py` — `collect`, `Run.last`, `Phase.status`, `Usage`
- `styre/config.py` 89-99 — `context_window(config_dir)`: how settings.json and models.json are
  read; read the model entry the same way
- `evals/bench.py` — Phase 3's `read_junit` and `score`

### Exit criteria
- With `FAKE_PI_DEFAULT=ok`: `result.json` has `new [1, 1]`, `keep [1, 1]`, `committed` 2,
  `exit_code` 0, a `run_id`, `usage.requests` > 0, `error` null, `model` `{"provider": "local",
  "id": "m", "base_url": "http://localhost:1/v1", "context_window": 1000, "thinking": null}`
  and the `--label` given
- With `FAKE_PI_DEFAULT=blocked`: `new [0, 1]`, `committed` 0, a non-zero `exit_code`, a
  `stopped` sentence, and the keep test still passes
- In the copy, `git log` has the start commit, the design commit and the phase commits, and
  nothing from the source repository's history
- A setup command that exits 1 gives `result.json` with `error` naming it, and no run
- Only `evals/bench.py`, `tests/test_bench.py` and `docs/decisions.md` are edited

### Gate
```
uvx ruff check .
uv run --with pytest python -m pytest -q
uv run --isolated --python 3.9 --with pytest python -m pytest -q
```

---

## Phase 5: The benchmark report

`python evals/bench_report.py PATH...` reads result files and prints one markdown report. A
`PATH` is a `result.json`, or a directory: its own `result.json` when it has one, else each
`*/result.json` one level down. Never search deeper: result directories hold whole repositories.

- **Group** the results by configuration: styre version, variant, `model.provider`,
  `model.id`, `model.context_window`, `model.thinking` and `label`, sorted. Each configuration
  gets a heading naming them, such as
  `## styre 0.25.0, brief, splash/mlx-community/Qwen3.8-27B-4bit, 120,000 ctx, splash 0.4`
  (leaving out what is null), a line `served: ...` when a result's `served` differs from
  `provider/id`, and a table: `Design`, `Started`, `New`, `Keep`, `Phases`,
  `Hours`, `Uncached in`, `Cached in`, `Cache hit`, `Output`, `Prefill h`, `Decode h`. One row
  per result, sorted by design, then start time. `New` is `15/17 (88%)`; `Keep` is `9/9`;
  `Phases` is `committed/phases`; a result with an `error` shows the error in place of the
  numbers it never reached.
- **A total row** per table: sums of passed and totals with the overall percentage, sums of
  hours and tokens, the cache hit over the summed tokens.
- **Below each table**: `Stops:` with one line per result whose `stopped` or `error` is set,
  and `Spread:` with one line per design that has two or more results in that configuration,
  such as `- todo-rules: new 15, 17 of 17; hours 1.10, 1.32`. This is the run-to-run noise any
  difference between configurations has to beat.
- **With more than one configuration**, a final `## Configurations` table: `Configuration`,
  `Results`, `Designs`, `New`, `Regressions`, `Hours`, `Uncached in`, `Cache hit`. Totals are
  only comparable over the same designs, so `Designs` lists them.
- Format numbers as `styre.summarize` does (`count`), and build tables with its `table`.

Where:
- `evals/bench.py` — the `result.json` keys (Phase 4, step 9)
- `styre/summarize.py` — `table`, `count`
- `tests/test_bench.py` — add the report's tests here, writing small `result.json` files by hand

### Exit criteria
- Two results of one design in one configuration give one table, a total row and a `Spread:`
  line naming both new counts and both hours
- Results from two configurations give two tables and a `## Configurations` table, whether
  they differ by styre version, by `model.id` or by `model.context_window` alone
- A result with an `error` is listed under `Stops:` and does not break the totals
- A directory holding `a/result.json` and `a/repo/deep/result.json` reads one result
- Only `evals/bench_report.py`, `tests/test_bench.py`, `evals/README.md` (a section on the
  two scripts) and `docs/decisions.md` are edited

### Gate
```
uvx ruff check .
uv run --with pytest python -m pytest -q
uv run --isolated --python 3.9 --with pytest python -m pytest -q
```
