# Parsed gate output waits for fix rounds

M3 was rescoped (2026-10-31) to acceptance tests and parsed gate output: the fix round would
get `file:line: message` entries from pytest, ruff, mypy, tsc and vitest instead of a raw
tail. The simplification pass then deferred the parsing. It feeds only the fix round, and the
six latest benchmark runs (three v1, three M2, on the reference host) had no fix rounds and no
failed styre gate command. Five parsers and a new module would have changed nothing measured.

## Consequences

Acceptance tests in the gate may make styre's gate fail more often. If M3's benchmark shows
fix rounds, parsed gate output comes back, built against captured output of each tool.
