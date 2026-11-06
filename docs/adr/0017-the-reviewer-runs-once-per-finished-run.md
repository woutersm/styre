# The reviewer runs once per finished run

v2's plan had the reviewer run at each milestone's end, inside a task graph. A design has no
milestones, so the reviewer runs once, after the run commits its last phase, over the whole
run's diff. This is the director's own rule: one review per finished design. A stopped run
gets no review; what stopped it is the person's to read first.

## Considered options

- After every phase: catches a bug before later phases build on it, at a Claude call per
  phase, and reviews code the next phase may change.
