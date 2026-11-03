# A split's parts run under the stalled phase's number

A split's 2 or 3 parts run as attempts of the stalled phase `n`, each with its own gate and
its own commit, titled `Phase n.1: ...`. They get no phase ids of their own: the run
directory, the timeline and `summary.md` see one phase `n`, with its time and tokens summed
over the parts and its last commit. Own ids (`3.1`) would have taken a sort key, file-name
parsing and a notes chain through `summarize` and the run loop, for a split that has never
run. Cut while simplifying M4 (2026-11-03).

## Consequences

Phase `n` can have two or three commits. If a real split shows the summed row hides what
went wrong in a part, per-part ids are the change to make.
