# A patch takes a second call

The advisor's first call has read-only tools (Read, Grep, Glob) and returns its action. Only
when that action is `patch` does styre make a second call with Edit, Write and Bash, given the
first call's diagnosis. An amend, split or stop therefore cannot leave edits behind. The cost
is one extra call per patch, at most two per run (ADR 0011).

## Considered options

- One call with edit tools, refused afterwards when the tree changed and the action is not
  `patch`: cheaper, but the read-only rule would be checked after the edits, not prevented.
