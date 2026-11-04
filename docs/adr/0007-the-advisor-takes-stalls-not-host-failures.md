# The advisor takes stalls, not host failures

styre calls the advisor for a stall: the gate still red after the fix rounds, a relay that is
stuck or too big, BLOCKED, a missing or contradictory state file, or no diff. A host failure
(an empty response, pi exiting non-zero, the idle timeout) ends the run as before. In a real personal
project's runs since styre 0.17 there were 9 stalls (7 "too big, split it", 1 BLOCKED, 1 no diff) and 16
host failures or interrupts; Claude can change a phase, not a model host, so an advisor call on a host
failure could only answer `stop`.

## Considered options

- Only a red gate and BLOCKED, the two the v2 plan named: leaves out "too big", the most
  common stall on record.
- Every stop: spends a frontier call to say what styre already knows.
