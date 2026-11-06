"""The per-phase prompts.

Only phase-specific material belongs here; the standing rules live in AGENTS.md, which pi
loads into every run. The prompt's fixed cost is amortised across phases, so it is worth
bytes: the honesty rules around `unmet_criteria` earn their space.
"""
import hashlib
from pathlib import Path

from styre.agents import AGENTS_BODY
from styre.config import DECISIONS


def template_hash():
    """A hash of everything fixed in the instructions an agent gets: this module's source and
    the AGENTS.md block. Recorded at run start, so a run whose prompts changed under it is
    recognisable afterwards rather than a mystery."""
    h = hashlib.sha256(AGENTS_BODY.encode("utf-8"))
    try:
        h.update(Path(__file__).read_bytes())
    except OSError:  # no source on disk; the AGENTS.md block alone still tells them apart
        pass
    return h.hexdigest()[:16]


def build_prompt(context, n, phase, notes):
    """The builder prompt: the design excerpt for this phase (see `design.phase_context`),
    the previous phase's notes, and this phase's criteria and gate stated plainly a second
    time.

    `docs/decisions.md` is deliberately **not** here, though the agent still writes it. It
    is the one thing styre used to forward to the next agent as fact without the gate ever
    seeing it — in a tool whose first rule is that the agent's account of its own work is
    never trusted. Measured on a real repo, most of a section restated what the tree already
    showed, the rest was status the gate had already proved, and none of it was about the
    phase that read it. `.styre/notes-next.md` is the phase-to-phase channel: addressed,
    forward-looking, and consumed rather than compounding. The log is for humans, in git.
    """
    criteria = "\n".join(f"- {c}" for c in phase.criteria)
    gate = "\n".join(f"  {c}" for c in phase.gate)
    return f"""You are implementing one phase of a larger design, unattended. AGENTS.md in this repository
holds the standing rules, what is checked after you finish, and the three files you write at
the end. Follow it; this prompt only adds what is specific to your phase.

The design's preamble, the list of its phases, and your phase in full. The phases before
yours reach you through the notes below and through the tree itself, not through their text.

<design>
{context}
</design>

<notes_from_the_previous_phase>
{notes or "(none)"}
</notes_from_the_previous_phase>

Your phase is: {phase.title}

Exit criteria. Make each one true and verify it yourself before you finish:
{criteria}

Gate. All must pass. Run them with `styre_gate` as you work; the orchestrator runs them again
afterwards and the phase only counts as done if they pass:
{gate}

When you finish, as AGENTS.md describes:

- {DECISIONS}, appending a "## Phase {n}: {phase.short_title}" section
- .styre/notes-next.md, overwritten
- then call `styre_finish`. DONE needs a green `styre_gate` run and no unmet criteria, and a
  criterion you could not verify is unmet.
"""


def planner_prompt(brief, window):
    """The planner prompt for `styre plan`: the frontier model adds implementation help to a
    brief and returns the whole design as text. `window` is the builder's context window,
    or None when styre cannot read it, in which case the sentence leaves out the size."""
    if window is None:
        window_clause = ""
    else:
        window_clause = f" and a context of {window:,} tokens"
    return f"""You are preparing a design for an unattended build. A local model, through the pi coding
agent, with read, bash, edit and write tools, no web access{window_clause}, will build it
one phase at a time. Each phase runs in a fresh process that sees only the design's preamble,
the list of phase titles and its own phase section, nothing from the phases before it except
the code they committed. Nobody watches, and it cannot ask questions. Everything it has to
look up costs it context and time, so write down what you can find out now.

The design below is a brief. Return the whole design with implementation help added. Keep
every line of the brief exactly as it is, the phases, their titles, exit criteria and gates
unchanged; add lines, never edit or remove them. Read the repository (Read, Grep, Glob) to
find what you add. Add only what is true of the repository as it is now.

For each phase, add under its text:
- a **Where** list: each file the phase edits or must read, with a line range and one line on
  what is there now, and the one existing test file it should copy from;
- an `### Acceptance tests` section, placed after the phase's text and before its exit
  criteria: one new test file, a line holding only its path in backticks, then a fenced block
  with the whole file. Write one test per interface the brief names for this phase (import it
  from the module the brief says, call it with the signature the brief gives, construct each
  error class with the arguments the brief shows) and one test per rule the brief states with
  an exact outcome (a sentence, an exit code, a refusal). Nothing the brief does not state.
  Use the repository's test framework and conventions, and put the file where this phase's
  gate command collects it. Each path must be new, and never a path another phase uses. If
  the brief already has an `### Acceptance tests` section, keep it as it is; you may add
  files to it. Put no skip or xfail marker in these files, not even for a platform: styre's
  test guard rejects an added one, so the phase could never be committed. The builder cannot
  edit these files and the gate's linter checks them, so follow the repository's lint rules,
  import order included;
- the exact signatures, types and constants it calls or changes, copied from the source;
- for every library the repository has not used before: the imports, the calls in the order
  the phase makes them and what each returns, in 15 lines or fewer, read from the installed
  package source (for example under `.venv/` or `node_modules/`), with the traps;
- the repository's conventions the gate depends on: test helpers and fixtures, how the
  tests are run, lint rules that bite;
- what the phase must not touch.

Do not write the phase's own code: a snippet shows a library's calls, never the change the
phase makes. Put what every phase needs in the preamble and everything else in the one phase
that needs it. Do not tell the builder to read a document: when a phase needs lines from one,
such as a README its tests check, quote those lines in the phase. Return the design in the
`design` field.

<brief>
{brief}
</brief>
"""


def _progress_block(progress):
    return f"""<your_progress_file>
{progress or "(empty: nothing was written to .styre/progress.md before this point)"}
</your_progress_file>"""


def advisor_prompt(stall, actions):
    """The advisor prompt for one stalled phase: the stall, what it can read, and the
    actions it may choose from, one line each, only those in `actions`. `stall` is read
    by attribute; `styre.advisor` imports this, so this module must not import it back."""
    action_lines = {
        "amend": ("- amend: the builder lacked a fact, a file, a signature or a rule. `text` is "
                  "what the builder reads before it starts again on the tree as it is now."),
        "split": ("- split: the phase is too big for one context. `text` holds 2 or 3 sections "
                  f"in the design format, titled `## Phase {stall.n}.1: ...`, `## Phase {stall.n}.2: ...`, "
                  "each with its text, a `### Exit criteria` list and a `### Gate` block. The last one "
                  "keeps the phase's gate, exit criteria and `### Acceptance tests` section unchanged. "
                  "The earlier ones get their own gate, green on their own work, and no acceptance "
                  "tests."),
        "patch": ("- patch: one hard part the builder will not get right. `text` is the diagnosis: "
                  "what is wrong and what to change. A second call makes the edit."),
        "stop": ("- stop: the design is wrong, or the stall needs the person. `reason` says what "
                  "the person has to decide."),
    }
    lines = "\n".join(action_lines[a] for a in actions)
    return f"""A local model, through the pi coding agent, built one phase of a design unattended, and
the phase stalled. Nobody is watching; the person reads the run later. You are the advisor:
you read the repository with Read, Grep and Glob, and you edit nothing. You answer once for
this phase.

The stall: {stall.reason}

<phase>
{stall.context}
</phase>

<progress>
{stall.progress or "(none)"}
</progress>

<gate_report>
{stall.gate_report or "(none)"}
</gate_report>

<uncommitted>
{stall.diff_stat or "(nothing uncommitted)"}
</uncommitted>

The phase's readable log is {stall.log}; its end is the most recent.

Choose one action, only these:
{lines}

The uncommitted work stays in the tree. The design file is not changed. You answer once
for this phase. `reason` is one paragraph for the person; `text` is empty for `stop` only.
"""


def patch_prompt(stall, diagnosis):
    """The prompt of the advisor's patch call: the diagnosis and the phase, and the rules
    for editing the tree so the gate passes. `stall` is read by attribute, as
    `advisor_prompt` reads it; `styre.advisor` imports this, so this module must not import
    it back."""
    gate = "\n".join(f"- {cmd}" for cmd in stall.phase.gate)
    return f"""A local model, through the pi coding agent, built one phase of a design unattended,
and the phase stalled. You have read the run and found one hard part the builder will not
get right. Now you make the edit yourself, in the tree as the builder left it.

The stall: {stall.reason}

<diagnosis>
{diagnosis}
</diagnosis>

<phase>
{stall.context}
</phase>

The phase's gate commands:
{gate}

Edit the working tree so the gate passes. Run the gate commands with Bash to check.
Do not edit, skip or delete tests: styre's test guard rejects it. Do not edit the
acceptance test files: styre writes them back. Do not commit, switch branches or touch
.styre/. Finish by returning a `summary` of what you changed.
"""


def advice_prompt(n, phase, advice, progress=""):
    """The prompt that runs a stalled phase again, attached after the phase's own prompt:
    the advisor's text, the progress file as the stalled attempt left it, and the tree it
    must start from — the attempt's work, uncommitted."""
    return f"""'{phase.title}' stalled and an advisor read the run. It is not a new phase:
the work so far is in the tree, uncommitted, and your progress file below is where the
last attempt got to. Start from the tree and the failure it left, not from the beginning.

The advisor's amendment — read it before you touch anything:

<advice>
{advice}
</advice>

{_progress_block(progress)}
"""


def fix_prompt(n, phase, failure, progress=""):
    """The fix-round prompt for a fresh pi process, attached after the phase's own prompt.

    It used to carry the failure and nothing else, so a fresh process knew what failed but not
    what the phase was: on 2026-09-28 a fix round for two lint errors began by grepping the
    design and re-reading the fixtures. The phase prompt now comes with it as the first
    attached file, and the agent's progress file says where the work got to.
    """
    return f"""Your work on '{phase.title}' did not pass verification. The first attached file is
the phase as you were first given it; the work itself is in the working tree, and your
progress file below says where it got to. Fix the problem below. Start from the failure, not
from the beginning: read only what the fix needs.

Do not drop features, do not skip, delete or weaken tests, and do not run git commit.
If the fix involved a real choice, append it to your section of {DECISIONS}.
Keep your progress up to date with `styre_progress` as you go. When finished, run
`styre_gate` and call `styre_finish` with the status and unmet criteria where you actually
got to.

{_progress_block(progress)}

{failure}
"""


def resumed_fix_prompt(n, phase, failure):
    """The fix-round prompt for a resumed session: the conversation already holds the phase,
    the work and the reasoning, so this adds only what failed."""
    return f"""Your work on '{phase.title}' did not pass verification when the orchestrator ran the
gate. Fix the problem below; everything else about the phase is as you left it.
Do not drop features, do not skip, delete or weaken tests, and do not run git commit.
When finished, run `styre_gate` and call `styre_finish` with the status and unmet criteria
where you actually got to.

{failure}
"""


def handoff_prompt(context, relay_at):
    """The one turn a stopped step gets, in its own session, before a fresh process takes over:
    its conversation is still in the server's cache, so writing down what it knows costs a
    minute, and the next process does not start blind (a real phase, 2026-09-28: the builder
    never wrote its progress file, and the first fresh start re-read the same eight files)."""
    return f"""Stop the work here. Your context has reached {context:,} tokens, past the {relay_at:,}
this phase is given, and a fresh process will carry on from your progress file — it knows only
what that file says, and it will not see this conversation.

Now, in this turn, call `styre_progress` — up to 40 lines in all; do not trim it to a count —
and do nothing else: no file, no command, no `styre_finish`. styre ends this process as soon
as the progress file is written.

Done: what is finished and in the tree, by file.
Now: the exact step you were on, and what is left of it.
Next: the remaining steps, in order.
Learned: every fact you had to find out that is not in the task — an API's real shape, a
  signature, a command that works, a trap you hit. The next process would otherwise find it
  out again.
"""


def relay_prompt(n, phase, progress, context, relay_at):
    """The prompt for a fresh start after a step's context outgrew the threshold, attached after
    the task it was on (the phase prompt, and the fix prompt when it was in a fix round)."""
    return f"""You are continuing '{phase.title}' in a fresh process. Your previous process had
filled its context to {context:,} tokens, past the {relay_at:,} this phase is given, and was
stopped between two turns — not because anything failed. Everything it did is in the working
tree; your progress file below is what it knew.

Carry on from where the progress file says you are. Do not start over and do not re-read what
it already records as done; check the tree only where you need to. Keep your progress up to
date with `styre_progress` as you go, and finish exactly as the attached task says.

{_progress_block(progress)}
"""
