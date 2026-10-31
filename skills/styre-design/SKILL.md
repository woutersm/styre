---
name: styre-design
description: Use when the owner wants to write a new styre design, turn an idea into phases a local model can build, or change a design after a stopped run. Also when the owner types /styre-design. Produces docs/<name>-design.md in the target repository, checked with `styre check` and approved by the owner. Running it is the /styre skill's job.
---

# Writing a styre design

You and the owner write a design that a local model will build through styre while nobody
watches. The builder cannot ask questions, so the design has to answer them in advance.
The owner decides what gets built and approves the design before it runs.

Read `../styre/writing-designs.md` before you write any phase, and `../styre/DIRECTOR.md` for
what you may do without asking. Never name either file in the design: `styre check` flags a
design that points the builder at a document, because the builder would read it into its
context.

## 1. Grill, and write the docs as you go

Interview the owner until every decision the design needs is settled. Map the decisions as a
tree: each answer opens the decisions that hang off it.

**Ask in rounds.** A round is every question whose prerequisites are already answered. Ask it
with the interactive question tool (`AskUserQuestion` in Claude Code), never as a list in
prose: up to four questions per call, your recommended answer as the first option with its
reason. A question that depends on another still open waits for the next round. Look up facts
yourself (files, tools, past runs); put only decisions to the owner.

**Write the docs as decisions settle**, not at the end:

- `GLOSSARY.md` at the repository root: each term the work uses, one or two sentences on what
  it is, and the words to avoid for it. Terms of this project only, no implementation detail.
  Create it with the first term; when it exists, use its words and challenge a conflicting one.
- `docs/adr/NNNN-slug.md`, numbered from the highest there: one short paragraph per decision
  that is hard to reverse, surprising to a later reader, and the result of a real trade-off.
  Add the rejected options when they are worth remembering. Skip a decision missing any of
  the three.

The glossary and the ADRs are the base of the design.

Cover at least:

- What should exist when this is done, and who or what uses it?
- What must it not do or change?
- How will a program check that it works? Tests, golden files from the old code for a
  port, or a command whose output can be compared.
- Which libraries, APIs or services does it touch, and are they already in the repository?

Stop when you could explain the work to someone who has never seen the repository. Say
back what you understood in five lines or fewer, and let the owner correct it. Commit the
glossary and ADRs on their own before you write the design.

## 2. Read the repository

Find every file the work touches. For each phase, note the file, the line range and what is
there now. Run `grep -rn` on each name the work changes and count the files it reaches.
Read the existing tests to learn how this repository tests. Run the gate commands you plan
to use once by hand, so you know they work and how long they take.

## 3. Cut the phases

Follow `../styre/writing-designs.md`. In short:

- Size a phase by the work it does, not by the length of its text. A phase that must open
  many files is a big phase however short it reads.
- Each phase's gate must pass on that phase's work alone, without a later phase.
- A phase that changes a backend and its UI together is already full. Put nothing else in it.
- Put the ripple last: a rename across many files is its own phase.
- For each external shape, give it in the text: an API's request and response, and for a new
  library the calls and what they return. The builder learns anything left out by trial.

Show the owner the phase list before writing the full text: title, what it builds, its gate,
and how many files it opens. Agree on the list first.

## 4. Write the design

Write `docs/<name>-design.md` in the target repository, in the format from the README: an
optional preamble, then for each phase a `## Phase N: Title` section with what to build,
a **Where** list, `### Exit criteria` and a `### Gate` code block. Keep the preamble to
what every phase needs, because every phase's prompt carries it.

When the interview wrote a glossary and ADRs, build the design from them. Use the glossary's
terms, and make each ADR's decision show in the phase it affects. Copy into the phase text
what the builder needs from them. Never name `GLOSSARY.md` or an ADR in the design: the
builder would spend its context reading them.

Check every path, line range, snippet and command in it against the repository.

## 5. Simplify it

Load the `styre-simplify` skill and run it on the design. It challenges each part for the
80/20 cut and puts every cut to the owner. Apply the accepted cuts before you check.

## 6. Check it

From the repository root, run `styre check docs/<name>-design.md`. Fix every error. Go through
each warning under "Worth a look" with the owner: change the design, or say why it can stay.
The prompt sizes are printed as well. A phase much larger than the rest is worth a second look.

## 7. Hand it over

Show the owner the final phase list and the `check` output. When they approve, commit the
design on its own. Then offer to start it with the /styre skill. Do not start a run without
the owner's go-ahead.

## Changing a design after a stop

The /styre skill reads the stop first. To change the phase that stopped, read its last
progress file (`summary.md` names it), add what the builder was looking for to the phase text
or split the phase, run `styre check` again, and commit the change on its own. Never edit a
design while a run is using it.
