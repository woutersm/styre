
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
