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


def build_prompt(context, n, phase, decisions, notes):
    """The builder prompt: the design excerpt for this phase (see `design.phase_context`),
    the accumulated decisions, the previous phase's notes, and this phase's criteria and
    gate stated plainly a second time."""
    criteria = "\n".join(f"- {c}" for c in phase.criteria)
    gate = "\n".join(f"  {c}" for c in phase.gate)
    return f"""You are implementing one phase of a larger design, unattended. AGENTS.md in this repository
holds the standing rules, what is checked after you finish, and the three files you write at
the end. Follow it; this prompt only adds what is specific to your phase.

The design's preamble, the list of its phases, and your phase in full. The phases before
yours reach you through the decisions and notes below, not through their own text.

<design>
{context}
</design>

<decisions_from_earlier_phases>
{decisions or "(none yet, this is the first phase)"}
</decisions_from_earlier_phases>

<notes_from_the_previous_phase>
{notes or "(none)"}
</notes_from_the_previous_phase>

Your phase is: {phase.title}

Exit criteria. Make each one true and verify it yourself before you finish:
{criteria}

Gate. All must pass. Run them as you work; the orchestrator runs them again afterwards and
the phase only counts as done if they pass:
{gate}

When you finish, write the three files AGENTS.md describes:

- {DECISIONS}, appending a "## Phase {n}: {phase.short_title}" section
- .styre/notes-next.md, overwritten
- .styre/phase{n}.state.json, with "phase": {n}

Re-read the rules for the state file in AGENTS.md before you write it. DONE with a non-empty
unmet_criteria is rejected, and a criterion you could not verify is unmet.
"""


def fix_prompt(n, phase, failure):
    """The fix-round prompt: one failure, fed back to a fresh pi process."""
    return f"""Your work on '{phase.title}' did not pass verification. Fix the problem below.
Do not drop features, do not skip, delete or weaken tests, and do not run git commit.
If the fix involved a real choice, append it to your section of {DECISIONS}.
When finished, rewrite .styre/phase{n}.state.json, raising "fix_rounds_self" by one and
updating "status" and "unmet_criteria" to reflect where you actually got to.

{failure}
"""
