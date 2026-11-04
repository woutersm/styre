# Split replaces a phase within the run

v2's plan had `split` add smaller tasks to a task graph. M3 kept v1's phases, so there is no
graph. In M4 `split` returns two or three phase sections that replace the stalled phase in
this run only, each built, gated and committed like any phase. It is built now, not when a
graph exists, because 7 of the 9 stalls in a real personal project's runs since styre 0.17 ended with styre's
own advice to split the phase.

## Considered options

- amend, patch and stop only, `split` waiting for the task graph: a smaller milestone, but the
  most common stall could then only be amended or stopped.
