# TODO

What is left, and what is deliberately not being done. The *reasoning* behind anything here
lives in `CLAUDE.md`; this file is the list, not the record.

Rewritten 2026-09-23 after the original T1–T8 list was worked through; checked item by item
against the code on 2026-09-30. Items that were only
a retelling of something CLAUDE.md now explains were dropped rather than archived.

---

## Open — in styre

- [ ] **A time limit per bash call** (~10 min), enforced by styre, not left to the builder.
      A hanging `uv run python` probe cost 2 hours on 2026-10-02 before the idle timeout fired.
- [ ] **On a stop, `summary.md` names the last progress file**, so its findings can be copied
      into the phase text before resuming (`skill/DIRECTOR.md` rule 3).

- [ ] **`styre summarize --compare runA runB`.** Two runs side by side per phase: agent time,
      peak context, restarts, fix rounds, styre tool calls. Needed to judge a change to styre
      itself, such as the agent tools of 2026-09-30, against the run before it.
- [ ] **Check the model host before phase 1.** A sleeping or unreachable host kills a run
      after preflight has passed (app, 2026-09-30: the model Mac was off the network that
      morning). `server.py` already reads modelhost's `/status`; preflight can ask it, or
      `/v1/models`, and refuse to start. No `--skip` flag.
- [ ] **Warn when another client is using the model host.** A second client on the same
      server (app's mail judge) slowed a styre run's decode by ~11% whenever they overlapped,
      and the client's own requests timed out (2026-09-30). styre cannot stop another program,
      but it can say so at the start of a run when `/status` shows active requests.
- [ ] **`check`'s new-dependency warning misreads names as packages.** On app's split design
      (2026-10-01) it flagged `create-app`, `deps.py` and `now` — a function, a file the phase
      creates, and an attribute — as libraries "this repo does not depend on yet", and asked
      for a usage snippet the phase already had. Match backticked names against the
      dependency manifest's own vocabulary, not any lowercase identifier.
- [ ] **No test uses real `uv`.** The fixture gate is `test -f done.txt`, so the end-to-end
      suite never exercises a slow, realistic gate. Low value; keep only if a gate bug slips
      through.

## Known limitations — understood, not scheduled

Write these down so they are not rediscovered at 3am. None is currently worth code.

- **A host that keeps talking but makes no progress is invisible to the idle watchdog.**
  `--timeout` measures silence. mlxserve's memory thrash (allocate ~11 GB, hit the limit,
  reclaim, repeat) printed throughout; modelhost's memory waits clear within a second
  (2026-09-30), so this has not been seen since the switch. A throughput detector would
  catch it and is not worth the complexity yet.
- **Notes last exactly one hop.** `notes-next.md` is the only phase-to-phase channel, so a
  Phase 1 decision that Phase 9 needs will not survive. The answer when it bites is to put
  it in the design by hand, not to put the decisions log back in the prompt.
- **The live renderer garbles parallel tool calls.** pi emits two `toolcall_start` events
  before either executes; `render_event` assumes strict interleaving, so arguments and
  check-marks land on one line (seen again 2026-09-30:
  `…app.lan /Users/…` followed by `✓ ✓`). Cosmetic — `events.jsonl` is correct.

## Parked — ask before starting

- Spend and time budgets, a placeholder scan, parallel phases, run notifications, a queue
  of designs (the director chains runs, `skill/DIRECTOR.md`).
- **Not again without a new reason:** hidden held-out tests (built 2026-09-29, removed the
  same day as more complexity than they were worth); anything that calls a model or makes
  a judgement — an automatic Claude escape hatch, an automatic review, a run narrative (all
  the director's, `skill/DIRECTOR.md`); a web viewer or live panel (`summarize` and the log are
  how a run is read).

## Done

- **2026-10-03** — the director agreement (`skill/DIRECTOR.md`), and styre cut to what needs no
  judgement: `touch.py` (`--claude-touch`), `claude_review.py`, `review.py` (`check`'s
  reference cross-check), `watch.py` and `server.py` removed with their tests; `CLAUDE.md`
  from 1,162 lines to the design record that still holds.

- **2026-09-30** — the agent's `styre_gate`, `styre_progress` and `styre_finish` tools;
  `run` and `check` refuse to start outside the repository root; `summarize` reports the
  versions of the latest invocation; `orchestrate.py` deleted; MIT license and packaging
  metadata for a first public release.
- **2026-09-29** — `summarize` believes a reported thinking count only when it is backed:
  mlxserve's `usage.reasoning` said 0 beside a 66,781-character thinking block, so a zero next
  to thinking blocks falls back to the character split (`thinking_tokens()`).
- **2026-09-23** — `styre check` prints a prompt size per phase and warns about the two
  shapes that fail: prose telling the agent to read a document, and an outsized phase. On
  app it flags exactly phases 2 and 9, and nothing else.
- **2026-09-23** — pi runs under styre's own config dir (`PI_CONFIG_DIR`), preflight
  enforces it, `run_start` records it. Fixed overhead 8,331 → 1,639 tokens.
- **2026-09-23** — an all-zero final `message_end` reports "the model returned an empty
  response" instead of blaming the agent. Earned itself the same day.
- **2026-09-23** — `review.py` caps identifiers at `MAX_HITS`; a 65 KB report became 26 KB
  of signal. `summarize` gained the commit sha and cache hits, lost three dead fields.
- **2026-09-22** — the decisions log is written but not transmitted. Prompt scoping, then
  deletion. `docs/` and `.styre/` read bans in `AGENTS.md`.
- **2026-09-22** — live logging: `[+MM:SS]` stamps, gate and commit narration, `phaseN.log`
  written through so `tail -f` follows a phase, and `--timeout` became idle rather than a
  deadline (closing T1).
- **2026-09-22** — simplification pass: `report.md`, the tools table, `touches.json` and
  `styre review` all removed; the Claude ladder collapsed to one touch; `runner.py` threads
  one `Ctx`.
- **T1, T2, T3, T4, T6, T7** — streaming with our own timestamps, session dir and name per
  step, `timeline.jsonl`, one directory per run, `styre summarize`, and the pytest suite
  against `fake_pi.py` / `fake_claude.py`.
- **Acceptance** — the full loop has run repeatedly against real pi on a real 12-phase
  design (app, a personal project), which is a harder test than `example-design.md` ever was.
