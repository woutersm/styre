# Memory is curated from the notes and the decisions log

After each green phase the curator reads the memory, the phase's `notes-next.md` and the
phase's new section of `docs/decisions.md`, and writes the memory again, at most 4,000
characters. This reopens a settled decision (2026-11-06, the owner's call): the decisions
log was written but never transmitted, because it is the builder's ungated self-report.
It now reaches later phases, but only through the curator, distilled and capped, and never
whole. The builder still writes the log, and no prompt includes it.

## Considered options

- Notes and the progress file's Learned line only: keeps the settled decision, but leaves out
  the log, the one place the builder writes why it chose what it did.
- The phase's diff: facts the gate proved, not claims, at up to ~25k tokens of prefill per
  phase on the local host.

## Consequences

A wrong claim in the log can become a memory fact that every later phase reads. The cap and
the curator's rewrite bound it; if a run shows a phase misled by its memory, this is the
decision to revisit.
