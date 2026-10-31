# No mechanical check that the gate collects acceptance tests

An acceptance test the gate's command never collects passes silently. styre does not verify
collection. The planner is told to put each file where that phase's gate command collects it,
and the person confirms it when reviewing the planned design. A mechanical check, such as
running each file once broken or matching parsed test names, would need a step per test tool;
M3's benchmark shows first whether the planner gets placement right.

## Consequences

If the benchmark shows uncollected acceptance tests, this decision is the one to revisit.
