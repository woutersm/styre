# The reviewer returns findings; styre writes and proves their tests

The reviewer has read-only tools and returns its findings as structured output: per finding
a title, a place, why it is wrong, and optionally a test file and a command that runs only
that test. styre writes the test files and runs each command on the finished tree. A non-zero
exit proves the finding. The reviewer never edits the tree, like the planner, whose design
styre also writes and checks. The fix phase's gate is the design's last gate, which was
green, plus the proven findings' commands, so the full checks still run before the fix
commits.

## Considered options

- The reviewer writes and runs its own tests with Write and Bash: fewer moving parts in
  styre, but a review could leave edits behind and run any command.
