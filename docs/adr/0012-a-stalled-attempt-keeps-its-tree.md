# A stalled attempt keeps its tree

After an amend or a split, the retry starts on the tree the stalled attempt left, with its
progress file. styre does not reset to the last commit. A stopped attempt in a real personal project's sources
design had already written 80% of the first half of the split that followed. The advisor
reads that tree and writes its advice for it.

## Considered options

- Save `git diff` to the run directory and reset: a clean start after a wrong turn, but the
  retry rebuilds work that was already there.
