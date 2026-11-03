# One advisor call per phase, two patches per run

A phase gets at most one advisor call; a split's new phases share their parent's. A phase that
stalls again after its advice, or whose patch leaves the gate red, stops the run as v1 did:
the advice was wrong, and reading why is the person's job. A run makes at most two patches;
past that, the advisor's schema has no `patch` and it picks amend, split or stop. Both limits
are constants. They bound frontier calls (at most three per stalled phase with a patch, one
otherwise) and keep the local model writing most of the code.

## Considered options

- Two calls per phase: the advisor sees its own advice fail and tries again, at twice the
  frontier cost of a hard phase.
- A `--max-patches` flag: a knob with one sensible value.
