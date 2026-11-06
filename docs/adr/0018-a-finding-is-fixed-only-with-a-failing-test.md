# A finding is fixed in the run only with a failing test

The reviewer writes a test for each finding it can test. styre runs it on the finished tree,
and only a test that fails there makes the finding a fixed one: the failure is the proof the
bug is real. styre then adds one fix phase to the run that makes those tests pass. A finding
with no test, or with a test that already passes, goes to the report only. This is the
director's rule for reviews, findings fixed with a test each, made mechanical.

## Considered options

- Report only: the run ends unchanged and the person fixes findings, as today.
- A brief for the next run: nothing changes without approval, but a fix waits a night.
