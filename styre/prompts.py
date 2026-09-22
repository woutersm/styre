"""The per-phase prompts.

Only phase-specific material belongs here; the standing rules live in AGENTS.md, which pi
loads into every run. The prompt's fixed cost is amortised across phases, so it is worth
bytes: the honesty rules around `unmet_criteria` earn their space.
"""
import hashlib
import re
from pathlib import Path

from styre.agents import AGENTS_BODY
from styre.config import DECISIONS

# Every "## ..." heading in the decisions log, not only the "## Phase N" ones. The design
# parser splits on phase headings alone and folds anything else into the phase above it;
# here that would smuggle a hand-written "## Post-run corrections" section into the prompt
# on the back of the phase it happens to follow.
_HEADING_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")


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


def scope_decisions(text, phases):
    """The part of the decisions log that belongs to *this* design.

    `docs/decisions.md` is per project and append-only, so a repo that has run more than one
    design accumulates every design's sections in it. All of it used to ship in every phase
    prompt. On one real repo that was 29.6 KB of a 38.4 KB prompt — 77% of what the local
    model read was another plan's history, and the model returned an empty response rather
    than the phase.

    The file stays whole on disk; it is the durable record, and that decision is unchanged.
    Only the sections whose `## Phase N: Title` heading matches one of this design's phase
    titles are transmitted. The agent is told to write exactly that heading (see
    `build_prompt`), so a match is the same string on both sides.

    Anything else — another design's phases, a hand-written note, the preamble — is dropped.
    `runner` prints how much, because a section silently missing from a prompt is the kind
    of thing that is only noticed at 3am.
    """
    titles = {p.title.strip() for p in phases}
    parts = _HEADING_RE.split(text)
    kept = [f"## {parts[i].strip()}\n{parts[i + 1].rstrip()}"
            for i in range(1, len(parts), 2) if parts[i].strip() in titles]
    return "\n\n".join(kept).strip()


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
