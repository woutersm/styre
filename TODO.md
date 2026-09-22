# TODO

Observability work for the `styre` package. Source: the task list in `HANDOFF.md`.

The orchestrator has since been split into modules behind a `styre check` / `styre run`
CLI, and T7's test suite exists. Put new work in the module that owns the concern, and
add cases to `tests/` rather than only checking by hand.

**T4, T3, T6 and T2 are done**: `styre/rundir.py` owns the run layout, `styre/timeline.py`
the record of what the orchestrator did, `styre/summarize.py` reads both back, and pi's own
sessions now land in the run directory. What is left is T5 (a pi preflight), the loose ends
in T1 and T7, and T8 if it is ever wanted.

T0 (get real pi working, capture JSON samples) is **done**: pi 0.85.1 works, samples are in
`tests/fixtures/`, and the verified event schema is in `CLAUDE.md`.

Keep every existing behavior working. Python stdlib only.

---

## T4. One directory per run — done

Logs used to append across runs and prompts were overwritten, so two runs could not be
compared. `styre/rundir.py` now owns the layout; `runner.py` asks it for every path.

- [x] ~~Create `.styre/runs/<YYYYmmdd-HHMMSS>/` at run start; put prompts, logs,
      events and the run's report under it.~~ Done: `new_run()`, `RunDir`. `RunDir.timeline` is
      the path T3 writes; T2 adds `sessions/` when it passes `--session-dir`.
- [x] ~~Move `notes-next.md` and the `phaseN.state.json` files into the run directory.~~
      Done, but **the agent's own paths did not move**. It still writes the short
      `.styre/phaseN.state.json` and `.styre/notes-next.md` that AGENTS.md names — a
      committed AGENTS.md cannot name a run id — and `collect()` moves both into the run
      directory once pi stops. `clear_inbox()` empties them before each run, so a stale file
      can never be read as this phase's result.
- [x] ~~A new run starts with no carried-over notes.~~ Done: notes are read from
      `<run>/phase{N-1}.notes-next.md`, which does not exist in a fresh run directory. They
      are stored per phase rather than as one overwritten file, so resuming at phase N reads
      what phase N-1 handed over even when a later phase already ran.
- [x] ~~Leave `docs/decisions.md` where it is.~~ Done, untouched.
- [x] ~~Write `.styre/latest.txt` containing the run id (a file, **not** a symlink —
      Windows).~~ Done, rewritten whenever a run is opened, new or resumed.
- [x] ~~`--from-phase N` continues in the latest run by default.~~ Done; it warns and starts
      a new run if there is no earlier one.
- [x] ~~Add `--run-id` to select a different run.~~ Done. An unknown id is a preflight error,
      not a silently created directory.
- [x] ~~Update the `.git/info/exclude` entries if the layout changes.~~ Nothing to do:
      `EXCLUDES` already carries `.styre/`, which covers `runs/`.

## T1. Stream pi output live, with our own timestamps — mostly done

pi's event docs show no per-event timestamps except the session header, so the orchestrator
has to stamp lines as they arrive.

- [x] ~~Replace the buffered `subprocess.run` for pi with `subprocess.Popen`.~~ Done:
      `stream_pi()`.
- [x] ~~Write each line immediately to the events file with our timestamp.~~ Done, as
      `{"ts": "<iso>", "line": "..."}`. stderr is merged into stdout, so there is no `stream`
      field; add one only if the two need telling apart.
- [x] ~~Verify `tail -f` against a long real run (checked only against a replayed fixture).~~
      Done 2026-09-22, and the gap it was hiding is fixed: the readable log used to be
      assembled in memory and written only when pi exited, so `tail -f` on `phaseN.log`
      showed nothing until the phase was over. It is written through now, covered by
      `test_the_readable_log_is_written_while_the_phase_is_still_running`.
- [x] ~~Kill the whole process tree on timeout.~~ Done: `run()` starts each child in its own
      process group and `kill_tree()` signals the group. Keep this when switching to `Popen`
      line reading. The trigger became **idle time** rather than a deadline on 2026-09-22
      (`_watch_idle`): the old one-shot `threading.Timer` killed a phase 2 h after it started
      however busy it was, while this file had always claimed it watched for silence.
- [x] ~~Keep returning the return code and an output tail.~~ Done: the readable transcript,
      not raw JSON. The log is for reading, `events.jsonl` is for parsing — do not merge them
      again.
- [x] ~~Leave gate commands on `subprocess.run`.~~ Done.

## T2. JSON mode, session directory and session name — done

- [x] ~~Invoke pi as
      `pi --mode json --session-dir <run>/sessions/phaseN --name "<run-id> phase N <step>" ...`~~
      Done in `run_phase`. One directory per phase, one session file per step inside it.
- [x] ~~Confirm `@file` works in JSON mode.~~ Verified against pi 0.85.1.
- [x] ~~Note the documented session-dir precedence.~~ In `CLAUDE.md`, under the pi reference.

Both flags were re-verified against real pi 0.85.1 before the code was written, not assumed:
`--session-dir` gets `<iso>_<uuid>.jsonl`, and `--name` lands in `session_info.name` on the
second line of that file. That probe also became `tests/fixtures/pi_usage.jsonl` — the first
fixture with **real** token counts (`input 1560, output 23, cacheRead 6144, reasoning 0`),
since every older one predates the provider fix and reads as zeros.

## T3. Timeline file — done

One JSON object per line in `<run>/timeline.jsonl`, appended and flushed as things happen.
Every entry carries an ISO timestamp. `styre/timeline.py` holds the writer; the full field
list is in `CLAUDE.md` under "The timeline".

- [x] ~~`run_start` — design file hash, hash of the prompt templates in the script, pi
      version, branch~~ Done, plus the run id, styre version, phase count, `from_phase` and
      `retries`. `pi_version` shells out to `pi --version` once per run.
- [x] ~~`pi_start` / `pi_end` — phase, step (`builder` or `fix N`), duration, return code~~
- [x] ~~`gate_start` / `gate_end` — command, duration, return code~~ Emitted by
      `guard.verify()`, which now takes a `timeline`.
- [x] ~~`guard_result` — the test-tampering guard's verdict~~ Done: `ok` and `problem`. It
      is **absent**, not false, when `--allow-test-changes` turned the guard off.
- [x] ~~`commit` — sha~~ Done, with the phase and subject.
- [x] ~~`phase_end` — status and reason~~ Done, plus `rounds`, `fix_rounds_self` and
      `unmet_criteria`, so T6 can compare self-corrected against visible rounds without
      reading the state files.
- [x] ~~`run_end`~~ Done: `exit_code`, `committed`, `stopped`.
- [x] ~~Survive a killed run.~~ `span()` writes its end event from a `finally`, and every
      line is flushed as it is written.

Note a resumed run appends to the timeline of the run it continues: one `run_start` per
invocation, not per directory. T6 groups by them.

## T6. `styre summarize [<run-dir>]` — done

A third subcommand in `styre/cli.py`, backed by a new `styre/summarize.py`. Stdlib only.
Reads `timeline.jsonl`, the events files and, if present, the session JSONL. With no
argument it summarises the run `.styre/latest.txt` names.

`timeline.jsonl` is the spine — durations, return codes and the commit sha come from there,
and the events files are only scanned for tools and tokens. So **T3 comes first**. Degrade
to a partial summary when a file is missing rather than erroring: a run that died mid-phase
is exactly the one worth summarising.

- [x] ~~Per-phase table: time in agent runs, time in gates, number of fix rounds, final
      status.~~ Done, with a totals row. `-` means nothing was measured; `0.0` means it was.
- [x] ~~Which gate command failed on each fix round.~~ Done. `gate_*` events are tagged with
      the phase and step at the producer, in `verify()`, rather than inferred by the reader
      from the preceding `pi_end`.
- [x] ~~Tool calls by tool name; tool errors; the longest tool calls, measured from our own
      timestamps.~~ Built, then cut back on 2026-09-22 to **tool errors only**, counted by
      tool name and surfaced in "where to look". The per-tool duration table (pairing by
      `toolCallId` across our own arrival stamps) was a quarter of `summarize.py` for
      something nobody read in the morning. Nothing in the summary is timed off the event
      stream now; durations come from the timeline, which we measure ourselves.
- [x] ~~Tokens from the `message_end` usage, never summing `message_update`.~~ Done: only
      `message_end` is read, input is the last value, output a sum.
- [x] ~~Per-step token split with `reasoning` optional and printed as "n/a", never `0`.~~
      Done, per phase and as a run total.
- [x] ~~A "where to look" list.~~ Done: failed gates, pi failures, guard verdicts, `BLOCKED`
      reasons, unmet criteria and failed tool calls, per phase.
- [x] ~~Compare `fix_rounds_self` against orchestrator-visible fix rounds.~~ Done, and a
      phase that committed cleanly still appears when that gap is there — it is invisible in
      the table, and it is the clearest sign of an under-specified criterion.
- [x] ~~Write `summary.md` into the run directory as well as printing.~~ Done.
- [ ] Parked: `--compare runA runB`. Nothing has needed it yet; two `summarize` calls and a
      diff answer the same question.

Keep this script deterministic. It must not call a model: counting tokens, measuring
durations and deciding which gate failed are exactly the things an agent's own account gets
wrong, and not trusting that account is the point of the orchestrator.

## Simplification pass, 2026-09-22

Five cuts, all landed, suite green:

- `report.md` is gone. `run` ends by printing and writing `summarize`'s own report, so
  there is one report format per run instead of two that could disagree. `PhaseResult`
  went with it: `run_phase()` now returns just the reason it stopped, or None.
- The tools table is out of `summarize.py` (437 → 387 lines); only tool *errors* survive.
- `touches.json` is gone; a phase's touch is counted off `touch_start` in the timeline.
- `styre review` is folded into `styre check` — one question, one command.
- The Claude ladder is one touch, not two. See CLAUDE.md, "Why one call and not two".
- `runner.py` threads one `Ctx` (design path, text, phases, opts, run dir, timeline)
  instead of six positional arguments per function.

## Context discipline, 2026-09-22 (evening)

Phase 3 landed first try after the prompt work; phase 4 then spent 8 steps and 18 minutes
reading `.styre/` — the timeline, `touches.json`, `review.md` — and wrote nothing.

- [x] ~~`AGENTS.md`: never read anything under `.styre/`.~~ The same fix as the design-doc
      line. An agent explores every path you name to it.
- [x] ~~Cap `review.py` at `MAX_HITS` hits per identifier, widen the exclusion list.~~ On
      app: 65 KB → 26 KB, and `conn` (111 hits), `clock` (93) and `Path` (36) stopped
      burying `WorkerConfig` (2). The report was bigger than the design it reviews.
- [x] ~~`summarize`: render the commit sha and cache hits; drop `Usage.written`, `.cost`
      and `.steps`.~~ The sha was collected off the timeline and never printed; cost is
      structurally 0 on a local provider.
- [ ] Delete `orchestrate.py`, the deprecated shim. Nothing references it but CLAUDE.md.
- [ ] Report an empty model response (`totalTokens: 0`) instead of "no state file written".
- [ ] `summarize`'s header takes versions from `starts[0]`; take them from the last
      invocation instead.

## Prompt scoping, 2026-09-22

Driven by a real failure on `~/Dev/app`: phase 3 stopped four times with "no state file
written". The actual event was the model returning **zero tokens** after ~4 minutes, at
~21k tokens of context. See CLAUDE.md, "Prompt size".

- [x] ~~Scope `docs/decisions.md` into the prompt.~~ Superseded the same day: **the log is
      no longer in the prompt at all.** Scoping it (29.6 KB → 2.6 KB on app) made the
      remaining 2.6 KB readable, and reading it settled the question — four of seven bullets
      restated the tree, one was status the gate had proved, none was about the phase that
      would read it. `scope_decisions()` was deleted with the block. The file is still
      written and still committed; `AGENTS.md` now says who reads it.
- [ ] Watch for the accepted risk: notes last one phase, so a Phase 1 decision that Phase 9
      needs will not survive eight hops. The fix when it bites is to put it in the design,
      written by a human — not to put the log back in the prompt.
- [ ] `styre check` should flag a phase whose prose tells the agent to read a file. That one
      line — "The design means `docs/agent-design.md`. Read it first" — turned a 2.3 KB
      phase into a 44 KB context and is invisible until the model goes silent.
- [ ] Report an empty model response honestly. A final `message_end` with
      `totalTokens: 0` is in the events file; styre says "no state file written", which
      cost four restarts to see through.
- [ ] `summarize`'s header takes versions from `starts[0]`. On a run resumed 8 times over
      two days it printed `pi 0.86.1, styre 0.2.0` while the run actually executed on
      0.87.0 / 0.7.0. Take them from the last invocation.

## Live logging, 2026-09-22

What a human sees while a phase runs. See CLAUDE.md, "Watching a run".

- [x] ~~Narrate the orchestrator's own steps: each gate command before it runs, its verdict
      and duration after, the test-guard verdict, and the commit with its sha.~~ A passing
      gate used to print nothing, so the terminal died for the length of the test suite.
- [x] ~~Stamp the agent's stream with time into the step (`[+MM:SS]`), on the lines that
      open one: a tool call and the start of a reply.~~ `process.elapsed()`.
- [x] ~~Write `logs/phaseN.log` through as it happens rather than at the end.~~ Closes T1's
      last open item.
- [x] ~~Make `--timeout` idle rather than a deadline.~~ `process._watch_idle()`.
- [x] ~~Make `fake_pi.py` emit `message_update.toolcall_start` the way real pi does~~ — the
      fixture had it and the double did not, so the stamp on tool calls was untested.
- [ ] Parked: a thinking heartbeat, and live per-step token counts. Both were offered and
      not taken; they add lines that say only "still alive". Revisit if a real run turns out
      to have long silent stretches the elapsed stamp does not explain.

## T8. Optional pi-written run narrative

A second, clearly separate layer on top of T6 — the numbers stay deterministic, pi only
writes prose about them.

- [ ] Add `styre summarize --narrate` (off by default) which calls pi once, non-interactively,
      after the deterministic summary exists.
- [ ] Feed it a *condensed* transcript, not raw logs: keep `session`, `message_end`,
      `tool_execution_start` / `tool_execution_end` and `agent_end`; drop every `*_update`
      event (they are cumulative deltas and account for ~75% of the bytes); drop `thinking`
      content blocks; truncate long tool results. Include the T6 `summary.md` and the
      `unmet_criteria` from the phase state files.
- [ ] Ask for one thing only: what went wrong and which exit criterion was probably missing
      or ambiguous, so the design's prompts can be improved.
- [ ] Cap the input size and skip narration with a clear message if a run is too large,
      rather than truncating silently mid-run.
- [ ] Write it to `narrative.md`, separate from `summary.md`, and label it as model-written.
- [ ] Run it with `--no-session` or into the run's own session dir, so narration does not
      pollute the phase transcripts.

## T5. Preflight check for pi

Note: `--list-models` currently returns only local mlxserve models and no provider key is set, so
a preflight that merely checks "pi replies" will pass while the run still has no capable
model behind it. Consider reporting the resolved provider/model in the preflight output.

- [ ] Before phase 1, run pi once with a tiny prompt ("reply with OK") under a short timeout.
- [ ] Fail fast with a clear message if it returns nothing, exits non-zero, or times out.
- [ ] On failure, print the likely causes: no provider configured (`pi --list-models` returns
      an empty list), missing provider key, or a run waiting on an approval prompt (add
      `--no-approve`).
- [ ] Add `--skip-preflight`.

## T7. Tests — mostly done

pytest, using a `fake_pi.py` test double installed as `pi` on PATH.

- [x] ~~Write `fake_pi.py`.~~ Done. It picks its action from the prompt file's base name
      (`phase1.prompt.md`, `phase2.fix1.md`, …) via `$FAKE_PI_PLAN`, so keep it in step with
      whatever T4 renames.
- [x] ~~Have the fake emit JSON events.~~ Done, modelled on `tests/fixtures/`, thinking
      included so the renderer dropping it is actually tested.
- [x] ~~Cover: the happy path; a gate failure then a successful fix; the test guard catching
      a skip marker; `BLOCKED`; a pi timeout; pi missing from PATH; resume with
      `--from-phase`.~~ Done in `tests/test_run_end_to_end.py`, plus a crashing agent, a
      dirty tree, a phase that stages nothing, and `DONE` with unmet criteria.
- [x] ~~Cover the new artifacts from T1–T6.~~ Run directories, the timeline, summarize and
      the per-step session files are all covered.
- [ ] No test uses real uv yet; the fixture gate is `test -f done.txt`, so the suite skips on
      Windows.

## Acceptance

- [ ] `styre run example-design.md` in a fresh git repo, with `fake_pi.py` as
      `pi`, ends with two commits. The run directory holds prompts, logs, sessions, events,
      `timeline.jsonl` and `summary.md`. Everything but the real-pi part is covered by
      `tests/test_run_end_to_end.py`; running it against real pi is the open half.
- [ ] While it runs, `tail -f <run>/logs/*.events.jsonl` shows lines as they arrive.
- [x] ~~`styre summarize <run-dir>` prints the table and writes `summary.md`.~~ Covered in
      `tests/test_run_end_to_end.py`; the parsers are tested against `tests/fixtures/` in
      `tests/test_summarize.py`.
- [x] ~~Two consecutive runs leave two directories under `.styre/runs/`, neither overwriting
      the other.~~ Covered in `tests/test_run_end_to_end.py`.
- [ ] The same flow works against real pi on `example-design.md`.
- [ ] Watch one real phase end to end with the new narration and see whether the elapsed
      stamps land where a tired reader wants them — the shapes are right against the
      fixtures, but only a real hour-long phase says whether it reads well at 3am.

## Parked — ask before starting

Hidden held-out tests, run and time budgets, a placeholder scan, parallel phases,
notifications when a run stops, a run-level circuit breaker on repeated Claude escalations.

(The reviewer agent came off this list on 2026-09-21 and was built as the Claude touch; see
CLAUDE.md, "The supervising layer". It was simplified from two touches to one on
2026-09-22.)
