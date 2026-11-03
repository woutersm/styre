# Advice stays in the run directory

An amend's text and a split's phases go into the retry's prompts and the run directory, and
the report shows them. styre never edits or commits the design file. The person approved that
file before the run (DIRECTOR rule 5: no design change without approval), and folds advice
into it afterwards if it should last.

## Consequences

A resume with `--from-phase` starts from the design as approved; it does not replay advice.
