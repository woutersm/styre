# A patch is marked by a neutral trailer

A phase commit that holds an advisor's patch carries the trailer `Styre-Advisor: patch`, and
the timeline and report say so too. The trailer names the role, not a model: the person's
rule is that no commit line names Claude, Anthropic or Claude Code. v2's plan said the
message names Claude; the trailer keeps the fact in `git log` without that.

## Considered options

- The report only: lost once the run directory is gone.
- "Written by Claude" in the message: breaks the person's commit rule.
