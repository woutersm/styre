
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

## Phase 3: Model calls in the report, and `bench.py --plan`

- `## Model calls` summarizes the run's `model_call` timeline events (written by `claude.call`
  in Phase 1) rather than a new usage type; the table is one row per role plus a total, and a
  run without `model_call` events omits the section entirely. A phase-less run (a `styre plan`
  run: `run_start kind: "plan"`, no phases) skips its phase/where-to-look sections in
  `render()` and `where_to_look()` so it summarizes without an error.
- In `bench.py --plan`, `frontier` is the sums of the **plan run's** `model_call` events
  (found via the copy's `.styre/latest.txt` after `do_plan`), not the `styre run` run's —
  the run made no frontier calls; `planned` is true only when the plan exited 0, and a
  failed plan records `error` and skips the run, leaving `hours` the `styre run` time
  (null when skipped).
- `bench_report` groups by `config_key` which now includes `planned`, so planned and
  unplanned results of one setup are two groups (old `result.json` files without the key
  sort as `None`, i.e. unplanned), and only a group with planned results gets the
  `Plan h` and `Frontier tok` (tokens in + out) columns, summed in the total row.

## Phase 1: Acceptance tests in the design format

- Parsing is line-oriented, not fence-scanning: `parse_acceptance` collects the indices of
  path lines (a line whose stripped text is a single backticked token), then searches for
  the first fence *strictly between* one path line and the next (or the section's end).
  This means a path line whose fence is malformed/missing gets `(path, None)` and a later
  fence can never be adopted by an earlier path.
- The repeated-path error reports the *second* occurrence ("Phase N repeats … from phase
  M"); if a path appears three times, each later occurrence reports separately against its
  first-seen phase.
- Windows drive letters are checked with a `^[a-zA-Z]:` prefix test in addition to
  `PurePosixPath.is_absolute()`, per the design's "or a Windows drive like `C:`".
- Content is kept exactly as inside the fence (no stripping), with the trailing newline,
  matching the gate's own fence handling.

## Phase 2: The planner writes acceptance tests

- **No `planner.py` change was needed.** The design said `problems()` is "read only"; it
  turns out the existing per-line body comparison already covers acceptance sections (they
  are part of the phase body), and its `validate(pph)` call already applies phase 1's
  acceptance errors to the planned design. The whole phase is one prompt bullet plus tests.
- **Prompt wording** follows the design's words; the test asserts on two or three phrases
  (`"### Acceptance tests"`, `"one test per interface the brief names"`, ...), not the full
  text, so later rewordings won't break it.
- **Fixture strategy for `run_plan`:** the conftest `DESIGN` has no acceptance section, so
  the plan-level tests use a local `acceptance_brief()`/`acceptance_planned()` pair built on
  it. `run_plan` gained a `brief=` keyword that swaps design.md *and commits it* — without
  the commit the dirty-tree preflight refuses the plan call, which was the trap that cost
  the first run of these tests.

## Phase 3: styre writes and restores acceptance tests in a run

- The phase-start write ignores its return value on purpose: a non-empty list there means a
  resume after a stop, not builder tampering, and logging it as `acceptance_restored` would
  be wrong. Only the write before each styre gate run (the one in `runner.py`'s loop, just
  before `verify`) records edits, prints `acceptance tests restored: ...` and emits the
  timeline event with `paths` (a list), `phase` and `step`.
- `acceptance.write` uses `open(..., newline="")` for both read and write rather than
  `Path.read_text/newline`: the project supports Python 3.9, where `read_text` takes no
  `newline` keyword. That is the only way CRLF content stays byte-for-byte.
- The builder's `styre_gate` tool (`pi_extensions/`) deliberately does not restore: a
  builder that edits an acceptance file gets a red styre gate after restoration and a fix
  round, which is the signal the report (phase 4) will count.

## Phase 4: Acceptance edits in the report

- `read_timeline` folds every `acceptance_restored` event's `paths` into
  `Phase.acceptance_edits` (one entry per path, per event), so a builder that
  re-tampered in each round shows as `(Nx)` via the existing `unique()` grouping.
- The "Where to look" line is `- acceptance test edited by the builder and restored
  ({times}x): {path}` — the exact wording the design fixed; no backticks around the
  path, unlike other lines.
- A phase with acceptance edits counts as a `problems` phase, so an otherwise
  committed phase that needed restoring still shows under "Where to look".

## Phase 5: Docs

- The design said to make "your checks" and "runs your checks" become "your gate" and
  "runs the gate". The second sentence is a passive clause in the README's first
  paragraph ("styre runs your checks itself"); I read "your gate" as the object of that
  clause and wrote "styre runs the gate itself", since "runs the gate" is the phrase the
  design names and "your gate" as object of "runs" would not parse there.
- CLAUDE.md's test-guard wording now reads "a stop until the v2 executor replaces it"
  with a parenthetical "(M3 kept v1's executor)" in Goal and scope, and "M3 kept v1's
  executor, so the stop holds" in the settled-decisions line. This records the decision
  rather than a milestone that no longer changes the answer.
- `docs/adr/` rows in the CLAUDE.md Files table and the `GLOSSARY.md` row describe the
  directories as the project's terms and the decisions behind the design; the ADR
  numbering is M3's, but the row is lifetime-stable, so it names the kind of file, not
  the count.

## Phase 1: The advisor's call and its checks

- `split_problems` short-circuits on a wrong phase count (1 or 4+): the title, validate and
  last-phase checks cannot line up, and the count sentence is returned alone.
- `check` reports a missing (not just blank) `text` for amend/split/patch as the empty-text
  sentence, per the design's single sentence; a non-string `text` is treated as `""`.
- `advisor_prompt` reads the `Stall` by attribute (not by type) so `styre/prompts.py` never
  imports `styre.advisor` back — the module would otherwise be circular.
- A `check()` refusal triggers the retry; a `claude.call` error (call failed) does not,
  mirroring `styre/cli.py`'s planner retry.

## Phase 2: Stalls go to the advisor: amend and stop

- `run_phase` now returns a `PhaseResult` and takes `advice`/`after`. A stalled attempt's
  `rounds`/`relays` are the phase totals (fix-round file names continue), but the limits
  (`--retries`, `MAX_RELAYS`) count the amended attempt's own work only, per the design's
  "the limits count the amended attempt's own". This is why the loop keeps private
  `own_rounds`/`own_relays` counters.
- The five stall kinds are everything in `run_phase` except the `rc != 0` branch and the
  empty-response branch, which are host failures (`stall=False`) and never reach the
  advisor.
- `PhaseResult.gate_report` holds the last gate failure's full report (the `full` half of
  `verify`'s result); an early stop before any gate run has `""`.
- `conftest.py`'s `styre` fixture now requests `fake_claude` and points `STYRE_CONFIG` at a
  settings file in `repo.parent`, so every stall in every end-to-end test reaches the fake
  `claude` (which prints nothing unless a test sets `FAKE_CLAUDE_REPLY`) and stops with
  "The advisor could not be asked: ...".
- `diff_stat()` stages before diffing because untracked files have no `--cached` diff until
  staged; the staged index is harmless, the phase commit block re-stages.

## Phase 3: Patch

- The commit block of `run_phase` moved into `commit_phase(ctx, n, phase, patched=False)`:
  it stages, applies the no-staged-diff rule, commits and writes the `commit` event in one
  place. The patch path passes `patched=True`, which adds the `Styre-Advisor: patch` trailer
  (`git commit -m` takes the blank line and trailer unchanged) and sets `patch=True` on the
  event; `summarize` reads that as `Phase.patched` and prints `committed (patch)`.
- A red patch gate stops the run with its own `phase_end` (status `stopped`) rather than
  going through a builder fix round — the phase's stall was already the last attempt of it,
  so no second `phase_end` for the same run.
- The patch call reuses the same `Stall` the decision call got (extracted as `make_stall`),
  so the diagnosis is answered against the same stall it was chosen for.

## Phase 4: Split

- `run_phase` gained `part=(k, Phase)` and `part_count`: a part runs under the stalled
  phase's integer number (so state/notes/log files stay per-phase), with its own `Phase`
  as `phase`, its gate and acceptance tests, and the stalled attempt's `after` counters so
  no fix-round or relay file is overwritten. The design excerpt is spliced:
  `phase_context(text, phases[:n-1] + [part] + phases[n:], n)`, so the index shows the part
  in the phase's place; `styre/design.py` was not touched.
- Part 1 keeps the progress file (like an amend) and reads `notes(n-1)`; the split notice
  rides in `phase{n}.advice.md` (file `phase{n}.split{k}.md` for the part's own prompt).
  Parts k > 1 call `clear_progress()` and read `notes(n)`, so part 2 gets part 1's notes and
  phase n+1 gets the last part's notes unchanged.
- On `split`, the runner deletes the stalled phase's acceptance files before running the
  parts: `check()` already guarantees only the last part may keep them, and the last part's
  `write_acceptance` puts them back at its start. A part stall stops the run naming the
  part's title, with no second advisor call (the parts share the parent's one-advice budget).
- The `advice` timeline event carries `titles` only for a split; `summarize` prints
  `- the advisor split it into: t1; t2` and stores 3-tuples for split entries in
  `Phase.advice`.

## Phase 5: Docs

- The "One phase" flowchart in `docs/architecture.md` now has one `advisor` node that the
  four stall edges (relay stuck, BLOCKED/missing state, no diff, retries used up) point at;
  its `stop` edge and its `amend or split`/`patch` edges are what keep the phase or end the
  run. The `stop` node keeps its `stop: work left uncommitted` label on the host-failure
  edge (pi exited non-zero or went silent), and the empty-response edge was split off the
  BLOCKED/missing edge, which it shared before M4.
- Wording choice: `CLAUDE.md` step 7 and the DIRECTOR/SKILL rule texts say "stall" for the
  builder-caused stops the advisor takes up, and "host failure" for the ones that still end
  the run — matching the milestone's vocabulary rather than inventing a new one.
- `CLAUDE.md` "Decisions that are settled": the "until a role exists" bullet now says the
  advisor (M4) takes what a stall needs and the director keeps reviewing a run until M5,
  instead of naming both as pending.
