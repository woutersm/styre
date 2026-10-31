# Acceptance tests live in the design

`styre plan` writes each phase's acceptance tests into the planned design, in an
`### Acceptance tests` section: a path, then the file's content in a code block. styre writes
the files into the repository when that phase starts, never earlier, so a later phase's tests
never fail an earlier phase's gate. The design stays the one file the person reviews before a
run, and the builder sees the tests in its prompt.

## Considered options

- Test files committed beside the plan under `.styre/acceptance/phaseN/`, copied in at phase
  start: a shorter design, but two places to review.
- The plan names each test in prose and the builder writes it: no new format, but the builder
  can misread a test the same way it misread the interface the test is for. M2's benchmark
  had five misses of that kind.

## Consequences

Each phase's prompt grows by the size of its tests, under the planner's 40,000-character cap.
