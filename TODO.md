# TODO

What is left, and what is deliberately not being done. The *reasoning* behind anything here
lives in `CLAUDE.md`; this file is the list, not the record.

Rewritten 2026-09-23 after the original T1–T8 list was worked through. Items that were only
a retelling of something CLAUDE.md now explains were dropped rather than archived.

---

## Open — in styre

- [ ] **`summarize` reads versions from the first invocation.** `Run.first` is `starts[0]`,
      so a run resumed eight times over two days printed `pi 0.86.1, styre 0.2.0` while it
      had actually executed on 0.87.0 / 0.11.0. Take them from the last `run_start`.
      (`styre/summarize.py:152`)
- [ ] **Delete `orchestrate.py`.** The deprecated shim. No code references it — only
      `CLAUDE.md`'s own file table and the two doc paragraphs describing it.
- [ ] **No test uses real `uv`.** The fixture gate is `test -f done.txt`, so the end-to-end
      suite skips on Windows and never exercises a slow, realistic gate.

## Open — outside styre

Not styre's code, but styre's problem when they are wrong. See CLAUDE.md, "Where the model
runs".

- [ ] **`models.json` `maxTokens: 32768`** — one turn may still be larger than the whole KV
      budget. With thinking capped at 8,192 a legitimate turn is ~12k; set **16384** as the
      backstop the thinking budget cannot bypass.
- [ ] **Raise `thinkingBudgets.medium` 8192 → 12288** once phase 6 of the current app run
      settles. The cap is now binding: phase 6 produced a turn of 8,256 output tokens where
      phase 5's largest was 6,376. Not back to 16384 — the runaway that started all this was
      ~19,600. If raising it only moves the ceiling, split the phase instead.
- [ ] **Pre-split `agent-todo.md` phase 9**, "The loop, **and** switching the gateway over",
      10 criteria. A title containing "and" is usually two phases; splitting phase 4 took it
      from three failures to a first-try commit.
- [ ] **Ask mlxserve why TurboQuant converts only 15 of 64 cache layers.** At full conversion,
      8-bit KV would be worth several more GB on a host that has none to spare.

## Known limitations — understood, not scheduled

Write these down so they are not rediscovered at 3am. None is currently worth code.

- **A thrash loop is invisible to the idle watchdog.** When the model host allocates ~11 GB,
  hits its hard limit, reclaims and repeats, pi keeps printing throughout — so `--timeout`,
  which measures silence, never fires. It is the one hang shape that keeps talking. A
  throughput detector would catch it and is not yet worth the complexity.
- **Notes last exactly one hop.** `notes-next.md` is the only phase-to-phase channel, so a
  Phase 1 decision that Phase 9 needs will not survive. The answer when it bites is to put
  it in the design by hand, not to put the decisions log back in the prompt.
- **The live renderer garbles parallel tool calls.** pi emits two `toolcall_start` events
  before either executes; `render_event` assumes strict interleaving, so arguments and
  check-marks land on one line. Cosmetic — `events.jsonl` is correct.
- **`preserve_thinking` was set to `false` mid-run**, at phase 10 of 12 with six first-try
  commits banked. Defensible on Qwen grounds — Qwen3 strips prior-turn thinking by
  convention — but the wrong moment to move a variable, and mlxserve's granularity is unverified.
  Revert first if a phase loops, forgets, or shows a jump in `fix_rounds_self`. Backup:
  `~/.config/pi/styre/models.json.bak-*`.
- **`usage.reasoning` is not trustworthy on mlxserve.** It reported `0` on a message carrying a
  66,781-character thinking block, so `summarize`'s Thinking column is not a measurement.
  Sum the `thinking` content blocks instead.

## Parked — ask before starting

- `styre summarize --compare runA runB`. Two `summarize` calls and a diff answer it.
- A thinking heartbeat and live per-step token counts in the terminal. Offered twice, not
  taken; they add lines that say only "still alive".
- **T8, a pi-written run narrative.** A `narrative.md` labelled model-written, on top of the
  deterministic numbers — never on top of them being wrong. `summarize` itself must keep
  calling no model.
- **T5, a pi smoke preflight.** Largely superseded: preflight now fails when styre's pi
  config directory is missing, which was the real failure mode. A "reply with OK" probe
  would still catch a dead model host before phase 1. No `--skip-preflight`; a flag whose
  only sensible value is its default does not earn its place.
- Hidden held-out tests, spend and time budgets, a placeholder scan, parallel phases, run
  notifications, a run-level circuit breaker on repeated Claude escalations.

## Done

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
  design (`~/Dev/app`), which is a harder test than `example-design.md` ever was.
