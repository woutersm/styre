"""The standing instructions written into the target repo's AGENTS.md.

pi discovers AGENTS.md on its own and loads it into every run, fix rounds included, so the
standing rules, the explanation of what gets checked and the three-file contract live here
rather than being restated in each phase prompt. A pre-existing AGENTS.md keeps its own
text; only the delimited block is replaced.
"""
from styre.config import AGENTS, BEGIN, DECISIONS, END

AGENTS_BODY = f"""{BEGIN}
<!-- Managed by styre. Edits inside this block are overwritten; text outside it is kept. -->

# Working in this repository

An orchestrator (styre) is running a phased design through you, unattended. Nobody can answer
questions, so resolve ambiguity yourself and record the decision. You are given one phase at a
time; each phase is a fresh process with no memory of the last one.

## What is checked after you finish

Your own account of your work is not what decides the phase. After you stop, the orchestrator
re-runs the phase's gate commands itself, and inspects the staged diff. A phase is accepted
only if every gate command exits 0, no test was skipped or deleted, and the phase actually
changed something. Then it is committed, one commit per phase. On failure you get the output
back and try again, a limited number of times, and the run stops if you do not converge.

So there is nothing to gain by reporting success early: the gate will find it, and you will
spend a fix round on it.

## Rules

- Implement only the phase you were given. Later phases are context, not work for now.
- Keep it simple. Write the plainest thing that meets the criteria and passes the gate. No
  configuration knob with one sensible value, no abstraction with one caller, no framework
  where a function will do, no option nobody asked for. A design that does not call for
  something is a design that does not want it.
- Search before creating: confirm a thing does not already exist, and edit it rather than
  adding a parallel version.
- No placeholders: no TODO, no stubs, no hard-coded results standing in for logic.
- When the phase lists tests, write them first, from that list, and watch them fail before
  you write the code they cover. A test that passes before its implementation exists is not
  testing what you think it is; fix the test. The list is the specification — never narrow it
  to what your implementation happens to do.
- Never skip, delete or weaken a test to make it pass; fix the code. Added skip/xfail markers
  and removed tests are rejected automatically.
- Keep a .gitignore for build artifacts.
- Do not run `git commit`, `git checkout`, `git reset` or any other command that moves the
  branch. The orchestrator owns the git history.
- Read what earlier phases wrote in the working tree rather than a description of it. The
  notes you are handed deliberately do not inventory the repository.
- **Read narrowly.** A file you read whole stays in your context for the rest of the phase,
  and tool results are the largest thing in it — 32-45% of a measured phase, with single
  reads of 5,000-6,000 tokens. Use `grep` to find the lines you need and read a range around
  them; read a file end to end only when you are about to rewrite it end to end. The same
  goes for a command's output: pipe it through `head`, `tail` or `grep` rather than printing
  a whole test log back into the conversation. Throughput falls as your context grows — the
  same phase decodes at 10 tokens a second early and 6 late — so this is your own speed you
  are spending, not just the machine's memory.
- **Never read anything under `.styre/`.** It is the orchestrator's working directory, not
  yours: run logs, timelines, prompts and other phases' files. Nothing in it helps you build
  this phase, and reading it spends the context you need for the work. Write exactly the two
  files your prompt names there, and nothing else — no listing it, no looking for another
  phase's state file to copy. The format you need is below, in full.

## The three files you write when you finish

| File | Lifetime | Who reads it |
| --- | --- | --- |
| `{DECISIONS}` | permanent, append-only, committed with the code | humans, later |
| `.styre/notes-next.md` | one phase; overwrite it, never append | the next phase only |
| `.styre/phaseN.state.json` | one phase | the orchestrator |

`{DECISIONS}` is for choices a reader could not infer from the code: ambiguities you
resolved, options you rejected and why, constraints you discovered. Not a list of the files
you created — the repository already shows that.

**Append to it without reading it.** It is append-only and nothing in it is addressed to
you, so open it only to add your section at the end — never to read what earlier phases
wrote. On a measured run, reading this file was the single largest tool result of the whole
run, ~14,000 tokens in one call, and it grows with every phase that has ever appended.

**No later phase reads it.** It is committed for a person going through this months from
now, so write the two or three things that would save them an hour, and nothing else. A
summary of what you built, a count of passing tests, or a report that the gate went green
is wasted here: the gate is what proves that, and it has already run. If the *next* phase
needs to know something, that belongs in `.styre/notes-next.md`, which it does read.

`.styre/phaseN.state.json` is the machine-readable result:

```json
{{"phase": 1, "status": "DONE" or "BLOCKED", "reason": "one line, required when BLOCKED",
  "unmet_criteria": ["exact text of each exit criterion you could not fully meet"],
  "fix_rounds_self": 0}}
```

`DONE` means every exit criterion is met and the whole gate passes, and requires
`unmet_criteria` to be empty. Listing both fails the phase, so use `BLOCKED` instead. A
criterion you worked around, partly met, or could not verify is unmet; so is one you are
unsure about. Recording that honestly is how the design gets fixed, and costs you nothing.
Claiming a criterion you did not verify is the one outcome that wastes the whole run.

`fix_rounds_self` is how many times you ran the gate, saw it fail and fixed it within the
phase. It is not held against you; it shows which criteria are hard to hit.
{END}
"""


def write_agents_file(path=AGENTS):
    """Create or refresh the styre block in AGENTS.md, which pi loads into every run. A file
    the project already had is preserved: only the delimited block is replaced."""
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if BEGIN in old and END in old:
        new = old[:old.index(BEGIN)] + AGENTS_BODY.rstrip("\n") + old[old.index(END) + len(END):]
    elif old.strip():
        new = old.rstrip("\n") + "\n\n" + AGENTS_BODY
    else:
        new = AGENTS_BODY
    if new != old:
        path.write_text(new, encoding="utf-8")
    return not old.strip()
