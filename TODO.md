# TODO

Observability work for the `styre` package. Source: the task list in `HANDOFF.md`.

The orchestrator has since been split into modules behind a `styre check` / `styre run`
CLI, and T7's test suite exists. Put new work in the module that owns the concern, and
add cases to `tests/` rather than only checking by hand.

Everything below writes into a per-run directory, so **do T4 first** — the other tasks need
its paths. T1–T3 can then be done in any order; T6 reads what they produce. T5 and T7 are
independent of all of it.

T0 (get real pi working, capture JSON samples) is **done**: pi 0.85.1 works, samples are in
`tests/fixtures/`, and the verified event schema is in `CLAUDE.md`.

Keep every existing behavior working. Python stdlib only.

---

## T4. One directory per run — do this first

Today logs append across runs and prompts are overwritten, so two runs cannot be compared.

- [ ] Create `.styre/runs/<YYYYmmdd-HHMMSS>/` at run start; put prompts, logs,
      sessions, events, `timeline.jsonl` and `report.md` under it.
- [ ] Move `notes-next.md` and the `phaseN.state.json` files into the run directory.
- [ ] A new run starts with no carried-over notes.
- [ ] Leave `docs/decisions.md` where it is: it is committed with the code and is deliberately
      per-project, not per-run.
- [ ] Write `.styre/latest.txt` containing the run id (a file, **not** a symlink —
      Windows).
- [ ] `--from-phase N` continues in the latest run by default.
- [ ] Add `--run-id` to select a different run.
- [ ] Update the `.git/info/exclude` entries if the layout changes.

## T1. Stream pi output live, with our own timestamps — mostly done

pi's event docs show no per-event timestamps except the session header, so the orchestrator
has to stamp lines as they arrive.

- [x] ~~Replace the buffered `subprocess.run` for pi with `subprocess.Popen`.~~ Done:
      `stream_pi()`.
- [x] ~~Write each line immediately to the events file with our timestamp.~~ Done, as
      `{"ts": "<iso>", "line": "..."}`. stderr is merged into stdout, so there is no `stream`
      field; add one only if the two need telling apart.
- [ ] Verify `tail -f` against a long real run (checked only against a replayed fixture).
- [x] ~~Kill the whole process tree on timeout.~~ Done: `run()` starts each child in its own
      process group and `kill_tree()` signals the group. Keep this when switching to `Popen`
      line reading.
- [x] ~~Keep returning the return code and an output tail.~~ Done: the readable transcript,
      not raw JSON. The log is for reading, `events.jsonl` is for parsing — do not merge them
      again.
- [x] ~~Leave gate commands on `subprocess.run`.~~ Done.

## T2. JSON mode, session directory and session name — partly done

The invocation is the constant `PI = ["pi", "-p", "--mode", "json"]` and the event stream is
parsed. The session directory and name are still not passed.

- [ ] Invoke pi as
      `pi --mode json --session-dir <run>/sessions/phaseN --name "<run-id> phase N <step>" ...`
      so each step's transcript lands next to that run's logs.
- [x] ~~Confirm `@file` works in JSON mode.~~ Verified against pi 0.85.1.
- [ ] Note the documented session-dir precedence: `--session-dir`, then
      `PI_CODING_AGENT_SESSION_DIR`, then `sessionDir` in settings.

## T3. Timeline file

One JSON object per line in `<run>/timeline.jsonl`, appended and flushed as things happen.
Every entry carries an ISO timestamp.

- [ ] `run_start` — design file hash, hash of the prompt templates in the script, pi version,
      branch
- [ ] `pi_start` / `pi_end` — phase, step (`builder` or `fix N`), duration, return code
- [ ] `gate_start` / `gate_end` — command, duration, return code
- [ ] `guard_result` — the test-tampering guard's verdict
- [ ] `commit` — sha
- [ ] `phase_end` — status and reason
- [ ] `run_end`

## T6. `styre summarize <run-dir>`

A third subcommand in `styre/cli.py`, backed by a new `styre/summarize.py`. Stdlib only. Reads `timeline.jsonl`, the events files and, if present, the
session JSONL.

- [ ] Per-phase table: time in agent runs, time in gates, number of fix rounds, final status.
- [ ] Which gate command failed on each fix round — usually the sign of a missing exit
      criterion.
- [ ] Tool calls by tool name; tool errors (`tool_execution_end` with `isError: true`); the
      longest tool calls, measured from our own timestamps between start and end events.
- [ ] Tokens and cost from the final `message_end` usage. Do **not** sum `message_update`
      usage — it is cumulative and can stay zero when a provider reports usage only at
      completion.
- [ ] Per-step token split: report `input`, `output`, and within output the thinking share as
      `reasoning` against non-thinking `output - reasoning`. `usage.reasoning` is optional —
      when the provider omits it, print "n/a", never `0`. Aggregate per phase and per run so
      a phase that burned its budget on thinking is visible.
- [ ] A "where to look" list: fix rounds and their reasons, `BLOCKED` reasons, and the
      `unmet_criteria` from each `phaseN.state.json`.
- [ ] Compare `fix_rounds_self` against orchestrator-visible fix rounds. A phase with high
      self-corrected rounds and zero visible ones hit a gate the design under-specified.
- [ ] Write `summary.md` into the run directory as well as printing.
- [ ] Optional: `--compare runA runB`.

Keep this script deterministic. It must not call a model: counting tokens, measuring
durations and deciding which gate failed are exactly the things an agent's own account gets
wrong, and not trusting that account is the point of the orchestrator.

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
- [ ] Cover the new artifacts from T1–T6.
- [ ] No test uses real uv yet; the fixture gate is `test -f done.txt`, so the suite skips on
      Windows.

## Acceptance

- [ ] `styre run example-design.md` in a fresh git repo, with `fake_pi.py` as
      `pi`, ends with two commits. The run directory holds prompts, logs, sessions, events,
      `timeline.jsonl` and `report.md`.
- [ ] While it runs, `tail -f <run>/logs/*.events.jsonl` shows lines as they arrive.
- [ ] `styre summarize <run-dir>` prints the table and writes `summary.md`.
- [ ] The same flow works against real pi on `example-design.md`.

## Parked — ask before starting

Reviewer agent, hidden held-out tests, run and time budgets, a placeholder scan, parallel
phases, notifications when a run stops.
