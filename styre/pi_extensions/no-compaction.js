// Cancel pi's automatic compaction under styre.
//
// Compaction asks the model to summarize the conversation and replaces it with the summary.
// On a local model host that is the most expensive thing a phase can do: the summary request
// is sent uncached, so the whole context is prefilled again (48k tokens, 8.5 minutes on mlxserve,
// 2026-09-27), and on a server without a thinking budget it does not work at all — modelhost
// thought until it hit the token cap and returned no summary, 16 times in one phase
// (2026-09-28), the first two attempts taking 26 minutes each.
//
// styre manages context itself instead: it restarts a phase that grows past its threshold in
// a fresh process that carries on from the agent's progress file (see styre/runner.py). A
// cancelled compaction is visible in the event stream, where `summarize`
// counts it.

export default function noCompaction(pi) {
  pi.on("session_before_compact", () => ({ cancel: true }));
}
