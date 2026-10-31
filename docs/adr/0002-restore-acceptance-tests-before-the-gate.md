# styre restores acceptance tests before every gate run

Before it runs a phase's gate, styre writes that phase's acceptance tests back from the
design, so the gate always runs the plan's version. A builder's edit to an acceptance test is
logged as a metric, not a stop: the restored test then fails the gate, and the fix round tells
the builder why. v1's test guard stays a stop for every other test until the executor is
replaced. v2's plan had it turn into a metric in M3, but the rescoped M3 (2026-10-31) keeps
v1's executor.

## Considered options

- Restore, and turn v1's guard into a metric now: the builder could then skip or delete its own
  tests, and only the report would show it.
- Stop on any edit to an acceptance test: strictest, but a test with a wrong reading of the
  brief would stop the run with no fix round.
