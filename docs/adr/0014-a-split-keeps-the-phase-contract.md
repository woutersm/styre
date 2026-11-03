# A split keeps the phase's contract

The last phase of a split keeps the stalled phase's gate, acceptance tests and exit criteria
unchanged; the advisor writes the gates and criteria of the phases before it. styre refuses a
split whose last phase changes any of the three. A split can then move work between phases
but cannot loosen what the person approved.

## Considered options

- The advisor writes every new phase's gate, checked only for being present: it could drop an
  acceptance test or a gate command.
