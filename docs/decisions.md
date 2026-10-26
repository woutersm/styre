
## Phase 1: Prefill, decode and cache hits in `summarize`

- A **request** is only an assistant `message_start` / `message_update`* / `message_end` chain:
  usage is summed at `message_end` where `message.role == "assistant"` only. The captured
  fixture shows why — `turn_end` (and `agent_end`) events carry a copy of the same usage
  block, so a `message_end`-only filter still double-counted output (126 vs the expected
  63). `message_start` for an assistant also carries a usage block (all zeros), but it is
  only read for its arrival stamp.
- `read_stamped_events` yields `(ts, event)` with `ts = parse_ts(wrapper.ts)` (None when
  missing/bad); `read_events` is now a thin wrapper that drops the stamp, and its
  docstring now says the stamp *is* read — for request prefill/decode — while phase
  durations still come from the timeline.
- `Usage.cache_hit` is `cache_read / (input + cache_read)`; None when there were no
  prompt tokens (rendered `-`, since "no prompt" is not a 0% hit rate).
- The `## Model time` table replaces the Phases table's `Cached` column entirely; its
  note moved there alongside the prefill/decode definition. `minutes(x, timed > 0)` gives
  the dash for untimed phases.

## Phase 2: `styre summarize --compare A B`

- The compare table is intentionally **not padded**, unlike `table()` elsewhere in the
  summary. The exit criterion demands a row that reads exactly
  `| 1 | Phase 1: One | committed → committed | 15.0 → 5.0 | ...`, and rjust-style padding
  would make that line un-greppable. Trade-off: the terminal is a little ragged; the win is
  that two compared runs can be diffed as plain text.
- Cell formatting is shared with the single-run summary: `minutes`, `count`, and the
  extracted `cache_hit_cell` (pulled out of `model_time_table` so both reports format a
  number the same way). `Fresh starts` and `Gate runs` are new cells but plain integers —
  `len(relays)` / `len(agent_gates)` — with no dash cases, since a phase that ran has a
  defined count of zero.
- The CLI's `--compare` path resolves each run with `rundir.resolve` (so a directory path
  works), prints, and writes no `summary.md`: a comparison is a check, and writing it into
  either run would fake a second summary that no single run produced.

## Phase 3: Scoring a reference suite from junit XML

- `evals/bench.py` provides `read_junit(path)` and `score(cases, keep_glob, expected_new,
  expected_keep)`, plus a small `main()` that scores one or more XML files from the command
  line (`--keep-glob`, `--expected-new`, `--expected-keep`); a later phase adds the run
  runner. stdlib only (`fnmatch`, `xml.etree`).
- `read_junit` returns `[]` for a missing file (`OSError`) or one that fails to parse
  (`ET.ParseError`), so a crashed part or a bad file simply scores as absent tests.
- The keep/new split is decided by matching the testcase **classname** (not the full id)
  against `"*" + keep_glob`, so it works for both pytest module paths
  (`test_keep_*`) and vitest file paths (`*.keep.test.*`).
- A test that never ran counts as failed only through `total = max(expected, seen)`;
  `failing`/`regressions` list only the ids that were actually seen and did not pass, and
  `missing` counts expected-not-seen tests across both kinds.

## Phase 4: Running one benchmark design

`evals/bench.py` gained `run_bench(design_dir, variant, styre_cmd, out, pi_config=None, label=None)`
implementing the nine design steps, plus a CLI in `main()`.

- **The pi config directory is resolved at call time, not import time.** `styre.config.PI_CONFIG_DIR`
  is computed when the module is imported, so reading it would silently pick up the developer's real
  config in a test that monkeypatches `STYRE_PI_CONFIG_DIR` after import. `pi_config_dir()` therefore
  re-reads `$STYRE_PI_CONFIG_DIR` each time, falling back to `~/.config/pi/styre`.
- **The clean copy is a fresh history-less clone.** `git clone` refuses a non-empty target, so the
  `repo` directory is pre-created empty first; a bare `git checkout <sha>` detaches on its own
  (`--detach` requires a pathspec). The finished work is thus unfindable in `git log` inside the
  copy.
- **The reference suite is copied in after the `git reset --hard` + `git clean -fdq`,** so it can
  never fail a phase gate during the run; conversely the gates in the benchmark design are changed
  to fail while the suite is present (`test ! -e bench_reference`), which is what the tests rely on
  to stop the agent before scoring. Tracked files (e.g. `docs/decisions.md`) survive the reset with
  their committed content, so keep tests on tracked files pass even after a blocked run.
- **`result.json` is written on every path, including early failures**; a failed run never reaches
  the keys for the steps it skipped, and they are `null`. The score's keys are merged in by
  `dict.update`, so a run that scored has real values and one that did not has the `null`s.

## Phase 5: The benchmark report

- `evals/bench_report.py` groups results by a tuple of the seven configuration fields (styre
  version, variant, provider, id, context_window, thinking, label); the `## Configurations`
  table is only added when at least two groups exist.
- A result with an `error` renders the error in the `New` cell and dashes for the columns it
  never reached; it contributes nothing to the total row (which sums only error-free results)
  but does appear in `Stops:`. `Stops:` lists each set `stopped` and `error` as its own line.
- `Spread:` prints `- <design>: new <passed[, ...]> of <total>; hours <h1, h2>`; the `of`
  total is shown only when every result in the group has the same total (the design's wording
  `new 15, 17 of 17`).
- PATH resolution is deliberately one level deep: own `result.json`, else each child dir's
  `result.json`. A child `repo/deep/result.json` is unreachable. `main` returns 1 (with a
  stderr message) when a PATH names no result.
- Cell formatting reuses `styre.summarize`'s `count`/`table`; cache hit is
  `cache_read/(input+cache_read)` at one decimal over summed tokens, matching `summarize`'s
  `cache_hit_cell`. Prefill/Decode hours are seconds/3600 at one decimal.

## Phase 1: `styre.json` and the Claude Code runner

- A failing `claude -p` can still print a well-formed result object (`is_error` true,
  `structured_output` null, non-zero exit — the budget fixture is exactly that). The runner
  therefore parses stdout before judging the exit code, so the quoted error wins over
  "failed with exit code N"; a non-zero exit that prints no JSON reports the exit code, a
  clean exit with unparsable output reports "not JSON".
- The timeout is a plain deadline (`communicate(timeout=...)` plus `kill_tree`), not pi's
  idle watchdog, because `claude -p` prints nothing until it ends; after the kill, draining
  the pipes also catches `OSError` — the child's pipes can already be dead.
- The developer's machine has a real `claude` on `PATH`, so every test must put the fake
  bin *first* on `PATH` (the `fake_claude` fixture returns that string; each test applies it
  itself) and clear `FAKE_CLAUDE_*` variables first. Tests that forgot this were flaky:
  the real binary answered in ~3.6s, just inside a 5s deadline.

## Phase 2: `styre plan`

- **The "brief untouched" test asserts the file equals the original brief, not the bad answer.**
  `cmd_plan` never writes the file after a failed retry (the `problems` branch returns first),
  so a test that feeds two bad answers must expect the brief back. The first version of
  `test_second_bad_answer_fails_cleanly` asserted the file held the bad answer and failed on
  that.
- **A retry answer that is byte-identical to the file commits nothing.** `git commit` exits
  1 with empty output when staging changed nothing, so `test_retry_prompt_after_a_gate_change`
  had its second reply be the genuinely-planned design (added lines), not the unchanged brief.
  The test also got a unique `replace` needle for *Phase 2's* gate — the first occurrence of
  the fence in the design belongs to Phase 1 — with a `changed != brief` guard.
- **The retry prompt is the first prompt verbatim plus "Your design was refused:" and the
  problem sentences**, one per line. Tests check the first prompt is a substring of the
  retry stdin.
- `planner.problems` compares gate and criteria *lists* in order, compares advisories as
  strings, and stops after a phase-count mismatch (the per-phase checks could not line up).
  The "dropped line" sentence names the place: `Phase n` for a phase's
  body, the preamble for one in the shared text.
- Docs: `README.md` gained a `plan` row in the Commands table and a section on what it does
  and commits; `CLAUDE.md`'s Files table names `styre/claude.py`, `styre/settings.py`,
  `styre/planner.py` and `tests/fake_claude.py`, and the `cli.py` row names `plan`.
