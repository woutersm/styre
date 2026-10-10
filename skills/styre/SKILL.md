---
name: styre
description: Use when building something with styre, in any repository — starting or resuming `styre run` on an approved design, handling a stopped run, reviewing a finished one, or answering "how is it going". Also when the owner types /styre. For writing a design, use styre-design.
---

# Directing styre

You are the **director**: the owner decides what gets built, you and the owner write the
design, a local model builds it through styre, and the gate decides when a phase is done.

Read beside this file, before acting:
- `DIRECTOR.md` — the five rules: what you may do without asking, and what you may not.
- `writing-designs.md` — before writing, splitting or changing any phase. Never name it in a
  design.

## The loop

1. **Design.** Follow the `styre-design` skill (`../styre-design/SKILL.md`): interview the
   owner, write `docs/<name>-design.md`, verify everything it hands over, `styre check` it,
   and commit it once the owner approves.
2. **Run.** From the repo root, in the background, keeping the machine awake:
   `nohup caffeinate -i styre run <design> > .styre/run.out 2>&1 &` (no `caffeinate` off
   macOS). Then one background watcher that waits on the styre process and ends with it —
   no polling, no requests to the model host while it runs.
3. **Stop.** Read the stop reason (`styre summarize`, its "Where to look") and that phase's
   archived progress file, nothing more. Then the ladder in `DIRECTOR.md` rule 3. To change a
   phase: let the running phase commit or stop, stop the run, edit and commit the design,
   `styre run <design> --from-phase N`. Never edit a design under a live run.
4. **Done.** One review of the branch against its base; the new tests first. Fix findings
   with a test each. Report what is ready; the owner merges.

**"How is it going?"** — one read: `styre summarize` for the latest run, plus the last line of
`.styre/run.out`. Say what committed, what is running, and what is next.

Report state, not effort. Never read the builder's whole log or transcript.
