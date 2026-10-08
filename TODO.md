# TODO

What is left, and what is deliberately not being done. The reasoning behind anything here
lives in `CLAUDE.md`; this file is the list, not the record.

## Open

- [ ] **A time limit per bash call** (~10 min), enforced by styre, not left to the agent.
      A hanging `uv run python` probe once cost 2 hours before the idle timeout fired.
- [ ] **On a stop, `summary.md` names the last progress file**, so its findings can be copied
      into the phase text before resuming (`skill/DIRECTOR.md` rule 3).
- [ ] **`styre summarize --compare runA runB`.** Two runs side by side per phase: agent time,
      peak context, restarts, fix rounds, styre tool calls. Needed to judge a change to styre
      itself against the run before it.
- [ ] **Check the model host before phase 1.** A sleeping or unreachable host kills a run
      after preflight has passed. Preflight can ask the provider's `/v1/models` and refuse to
      start. No `--skip` flag.
- [ ] **`check`'s new-dependency warning misreads names as packages.** It has flagged a
      function, a file the phase creates and an attribute as libraries "this repo does not
      depend on yet". Match backticked names against the dependency manifest's own
      vocabulary, not any lowercase identifier.

## Known limitations

Understood, not scheduled. None is currently worth code.

- **A host that keeps talking but makes no progress is invisible to the idle watchdog.**
  `--timeout` measures silence. A model server in a memory-thrash loop prints throughout. A
  throughput detector would catch it and is not worth the complexity yet.
- **Notes last exactly one hop.** `notes-next.md` is the only phase-to-phase channel, so a
  Phase 1 decision that Phase 9 needs will not survive. The answer when it bites is to put
  it in the design by hand, not to put the decisions log back in the prompt.
- **The live renderer garbles parallel tool calls.** pi emits two `toolcall_start` events
  before either executes; `render_event` assumes strict interleaving, so arguments and
  check-marks land on one line. Cosmetic: `events.jsonl` is correct.
- **No test uses a real, slow gate.** The fixture gate is `test -f done.txt`.

## Parked: ask before starting

- Spend and time budgets, a placeholder scan, parallel phases, run notifications, a queue
  of designs (the director chains runs, `skill/DIRECTOR.md`).
- **Not again without a new reason:** hidden held-out tests (built and removed as more
  complexity than they were worth); anything that calls a model or makes a judgement, such
  as an automatic escape hatch, an automatic review or a run narrative (all the director's,
  `skill/DIRECTOR.md`); a web viewer or live panel (`summarize` and the log are how a run
  is read).
