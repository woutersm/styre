---
name: styre-simplify
description: Use after a styre design is written and before it is approved, or when the owner wants an existing design challenged for simplification. Also when the owner types /styre-simplify. Finds the 80/20 cuts (the parts of a design that cost much and buy little) and puts each one to the owner.
---

# Simplifying a styre design

A design costs a night of local-model time per phase, and every mechanism it adds stays in the
code for good. Challenge the design before it runs: find the parts that cost much and buy
little, and offer to cut them. Start simple; add back what a benchmark or a stop shows is
missing.

The owner decides every cut. You find them, rank them and ask.

## 1. Read what the design rests on

Read the design, and the `GLOSSARY.md` and `docs/adr/` it was built from, when they exist.
Read the evidence it cites: a benchmark result, a stop, a lesson. A part with no evidence
behind it is the first thing to question.

## 2. Find the cuts

Go through the design phase by phase and part by part. For each part, ask:

1. **What measured problem does it fix?** Name the benchmark miss, the stop or the lesson.
   No answer means it is a candidate to cut.
2. **What is the smallest version that still fixes it?** One tool instead of five, one rule
   instead of four, a sentence in a prompt instead of a mechanism, a metric instead of a stop.
3. **Can it wait?** If the next benchmark would show whether it is needed, defer it and say
   which result would bring it back.
4. **Does it add a knob, a module, a format or a field?** Each one is code to keep. A knob
   with one sensible value, an abstraction with one caller, or a validation for a case nobody
   has hit is a candidate to cut.
5. **Does it duplicate something that already exists?** An existing check, test, prompt rule
   or report line may already cover it.

Never offer to cut a safety rule: styre runs the gate itself, never commits on red, and asks
the person before anything live. When simplicity and safety conflict, safety wins.

## 3. Rank them

For each candidate, write down:

- what it removes: phases, files, functions, fields, lines of design text;
- what is lost, in one sentence;
- the evidence for and against, with numbers where they exist;
- what would bring it back.

Rank by work removed for value lost. Keep the top cuts, at most eight. A cut that removes
little is noise: leave it out.

## 4. Ask

Put the cuts to the owner with the interactive question tool (`AskUserQuestion` in Claude
Code), up to four per call, never as a list in prose. For each cut, the first option is your
recommendation with its reason, the other is to keep the part as it is. Say what each cut
removes in the question itself.

## 5. Apply

For each accepted cut:

- change the design, and the glossary when a term goes away;
- record the cut as an ADR when it meets that bar (hard to reverse, surprising later, a real
  trade-off), naming what would bring the part back;
- when a deferred part belongs to a milestone plan, note it there.

Then run `styre check` on the design again and show the owner the new phase list and prompt
sizes beside the old ones.
