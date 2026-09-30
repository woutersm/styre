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


def _progress_block(progress):
    return f"""<your_progress_file>
{progress or "(empty: nothing was written to .styre/progress.md before this point)"}
</your_progress_file>"""


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
    minute, and the next process does not start blind (app phase 3, 2026-09-28: the builder
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
