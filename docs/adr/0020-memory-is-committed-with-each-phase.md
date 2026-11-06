# Memory is committed with each phase

`docs/memory.md` lives in the target repository and is committed. The curator runs after a
phase's gate passes and before its commit, so each phase commit carries its own memory
change. The person reads it in git and in review, and it outlasts a clone and its run
directories.

## Considered options

- `.styre/memory.md`, uncommitted: no extra lines in phase commits, but lost with the clone
  and invisible in review.
