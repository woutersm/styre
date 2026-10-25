
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
