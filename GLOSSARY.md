# styre

styre gets a design built while nobody watches: a local model builds it one phase at a time,
a frontier model makes the few judgement calls at fixed points, and the gate decides what is
committed.

## Designs

**Design**:
A document split into phases that styre runs. The unit the person approves before a run.
_Avoid_: spec, plan document

**Brief**:
A design without the implementation help: the phases, gates and every interface the tests
check, written by the person.
_Avoid_: outline, draft

**Planned design**:
A brief after `styre plan` added the implementation help and acceptance tests, keeping every
line of the brief.
_Avoid_: plan (as a noun for the file)

**Phase**:
One section of a design, built by one fresh builder process and committed as one commit.
_Avoid_: step, task, stage

**Exit criteria**:
Statements in a phase the builder must make true. Prose for the builder; styre does not run them.

**Gate**:
The commands at the end of a phase that styre runs itself before it commits. Green means the
phase may be committed.
_Avoid_: check (for the commands), CI

**Acceptance test**:
A test in a phase's section of the design, for an interface or a rule the brief states. The
planner or the person writes it, and it runs in that phase's gate.
_Avoid_: reference test (that is the benchmark's), spec test

**Reference test**:
A test from the benchmark's held-out suite. It runs once after a benchmark run ends, never
during one.
_Avoid_: acceptance test, hidden test

## Runs

**Run**:
One `styre run` of a design, from preflight to the last phase or a stop, with its own run
directory.

**Fix round**:
Another builder process for a phase whose gate failed, given the failures.
_Avoid_: retry (for the round), repair

**Relay**:
A fresh builder process that continues a step from its progress file when the context fills.
_Avoid_: compaction, restart

**Stop**:
The end of a run before the last phase, left for the person to read.
_Avoid_: crash, failure (for the run as a whole)

## Roles

**Builder**:
The local model, through pi, that does a phase's work.
_Avoid_: agent (when the role matters), worker

**Planner**:
The frontier model, through Claude Code, that turns a brief into a planned design.

**Advisor**:
The frontier model, called when a phase stalls, choosing one of a fixed set of actions.

**Reviewer**:
The frontier model, called at a milestone's end to review the committed work.

**Person**:
Whoever approves the design before a run and reviews the result.
_Avoid_: user, owner, operator
