# Writing a design for styre

The format is in `CLAUDE.md` under "Design file format"; this is about the *shape* of what
goes in it. Every rule below cost a night, and each one names the run it came from.

⚠️ **This document is not for the agent.** Do not name it in a design, and never write
"read `writing-designs.md`" into a preamble — `advisories()` flags a design that points its
agent at a document, for the reason in CLAUDE.md under "Prompt size". This is for whoever
writes the design, before the run.

## The unit of a phase is work, not prose

A phase's prompt is not what fills its context. Measured on app run `20260923-211043`
(styre 0.12.0):

| | prompt | reads | edits | peak context | outcome |
| --- | --- | --- | --- | --- | --- |
| Phase 1, a pure function in one new module | 8.9 KB | 4 (29 KB of results) | 11 | 50,669 | committed in 57 min |
| Phase 2, a migration plus its ripple | 7.9 KB | 25 (158 KB of results) | 15, 3 of them erroring | **130,901** | rejected after 2h37m |

The prompts are the same size. The phases are not. Phase 2's 25 `read` results alone were
~43k tokens, a third of its peak, and the host refused the prefill at `kv_len=129344`
(`predicted peak would exceed prefill safety cap 37.8GB`) — the empty-response failure in
CLAUDE.md under "The host runs out of memory long before it runs out of context".

So size a phase by the work, and estimate the work before the run:

- **Count the sites.** `grep -rn` every identifier the phase has to change. Phase 2's design
  named ten modules; the grep found **131 matching lines across 16 files**. That number was
  available before the night was spent.
- **Count the files it must open.** Each one is 5-7k tokens of `read` result, and a file
  re-read after an edit costs it twice.
- Against CLAUDE.md's measured rate — roughly a minute per 1,000 tokens of peak context,
  decode halving from 23 to 12 tok/s as context grows — a phase aimed at 50k is an hour and
  a phase aimed at 130k does not finish at all.

### Aim for under 60k, and stop bothering below 30k

The cost of context is not linear, and neither is the saving. Decode rate against peak
context, measured over two runs on the same host (2026-09-25):

| peak ctx | 14k | 19k | 28k | 48k | 51k | 72k | 77k | 86k | 96k | 131k |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tok/s | 10.7 | 9.2 | 10.7 | 10.1 | 9.3 | 8.6 | 8.0 | 7.6 | 6.2 | refused |

Cutting 96k to 48k bought **4 tok/s**. Cutting 48k to 14k bought about **half of one**, and
the ordering falls apart down there — the 19k phase ran slower than the 28k one. Below
roughly 30k the rate is set by per-turn prefill and speculative-decode acceptance rather
than by KV size, so the curve is flat and the measurements are noise.

Two things follow. **Splitting a 90k phase is the best change available to a design**, and
it pays twice: the rate is higher and each half writes less. **Splitting a 30k phase buys
nothing** — the wall time drops only because each half does less work, and you have paid a
phase boundary, a prompt, a gate run and a handoff for it. A phase is not too big because it
is 30k; it is too big when its gate cannot be green on its own work, which is the rule
above.

**Large edits are their own risk.** pi applies an `edit` call atomically, so a batch of nine
that trips on one hunk applies none of them; phase 2 spent three rounds re-issuing edits
piecemeal, each round re-reading the file it had just failed to change.

## A phase's gate must be green on that phase's work alone

This is the boundary test, and it decides where a phase ends more reliably than topic does:
**if cutting a phase leaves the suite red, the cut is in the wrong place.** Nothing is
committed on a red gate, so a phase that cannot pass on its own is not a phase.

That rules out the obvious cut as often as not. Splitting app's phase 2 into "the
migration" and "the ripple" looked right and was not: the tick's send-once filter is
`reminded_at IS NULL` until phase 5 moves it onto the new table, so dropping that column
in an early phase breaks a suite no phase in between is scoped to fix. The honest options
are a throwaway shim or a different boundary.

**Prefer expand / migrate / contract.** Each step passes the full suite:

1. **Expand** — add the new table, column or function beside the old one. Backfill here,
   while the old columns still exist; it is the last phase that can read them.
2. **Migrate** — move the consumers over, one phase per consumer if they are big.
3. **Contract** — delete the old thing and every name that mentions it.

Applied to app, phase 2 became "The schema, additively" (two modules, additive, backfill
included) and a new phase 6 became "Drop the old columns and follow through", placed after
the tick had moved. Same total work, seven phases instead of six, every gate green alone.

## The ripple gets its own phase, and it goes late

"Rename this and follow through everywhere" is the shape that blows up: it fans out to every
caller, and the agent has to open all of them. Give it a phase of its own, and place it
**after** the consumers have moved, where it is mechanical deletion rather than deletion plus
redesign.

When an early phase touches a module that a later phase reworks, say so and bound it:
*"do the minimum that makes the gate green; reshaping the matcher is Phase 7's job."*
Otherwise the work is done twice, and the first time is the one that runs out of memory.

## Say what the phase must not touch

"Nothing outside `src/app/db.py` and `src/app/store.py` is edited" is an exit criterion, is
checkable in the staged diff, and bounds how much of the tree the agent reads looking for
work. The same sentence in prose is a hint; in the criteria list it is the contract.

## Write criteria that match what the gate already proves

The gate is the arbiter, so a criterion earns its space by telling the agent something the
gate cannot say — *which* rows, *which* file, *what* the assertion looks like.

Watch `fix_rounds_self` in `summary.md`. App's phase 1 committed on the first orchestrator
attempt with **six self-fix rounds** inside it: the agent found and fixed six things the
criteria stated less plainly than the gate enforced. That gap is invisible in the commit and
is the clearest signal that a criterion needs rewriting before the next run.

Also, from CLAUDE.md's advisories: keep criteria to **8 or fewer**, make each one an
observable fact, and never ask for a skipped or xfailed test — the guard rejects the marker
and the phase fails for doing what the design said.

## Run any DDL or command the design hands over, once, before shipping it

Ordering constraints are invisible in prose. App's phase 2 shipped a migration that dropped
`todos.remind_at` while `idx_todos_open_remind` still indexed it, which SQLite refuses; the
agent discovered `DROP INDEX` had to come first and spent context on it. One `sqlite3` run
against an empty database would have caught it. The same goes for a gate command: run it on
the current tree so the phase does not open on a failure it did not cause.

## Reading a stop, and turning it into a design change

| What styre reports | What it usually is | The design fix |
| --- | --- | --- |
| "the model returned an empty response" | the host refused the prefill: the phase's context outgrew KV | split the phase; check `max(totalTokens)` in `summary.md` against the last phase that committed |
| gate still red after `--retries` | the design contradicts the repo — a fixture, a frozen assertion, a name already taken | patch the design, not the phase; `styre check`'s reference review is where this shows up before the run |
| guard rejected the diff | the design asked for a skip marker, or for deleting tests | reword the criterion; the guard outranks the human here by design |
| timed out while still printing | memory thrash on the host — forward progress stopped, output did not | the idle watchdog cannot see this one; it is the same fix as the first row |

`styre summarize` is the input to all four. Read the peak context of the phase that failed
and of the last one that worked: the difference is the size of the split you need.

## Before the run

1. `styre check <design>` — clean, and read the reference review rather than skimming it.
2. For each phase: `grep -rn` its names, and count the files it must open.
3. For each phase: would its gate be green with only that phase's work applied?
4. Any phase naming more than a handful of modules is a ripple — is it late enough?
5. Run the DDL and each new gate command once, by hand.
