# A failed curator call keeps the old memory

Every other model call that fails after one retry stops the run. A curator call that fails
after one retry leaves `docs/memory.md` as it was, and the run continues; the timeline and the
report say so. Memory is not a safety rule: a stale memory costs a later phase some looking
up, and a stopped night run costs the night.

## Considered options

- Stop the run, as the runner rule says: consistent, but stops for something no gate depends on.
