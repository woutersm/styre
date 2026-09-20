"""Parsing the design document.

Any preamble, then one block per phase:

    ## Phase 1: Title
    What to build.

    ### Exit criteria
    - a statement the agent must make true

    ### Gate
    ```
    uv run pytest -q
    ```

Exit criteria are plain prose for the agent. The gate is what the orchestrator enforces.
A phase with no criteria list or no gate block is a hard error.

A phase's prompt gets `phase_context()` rather than the whole document: the preamble every
phase needs, an index of the phase titles, and its own section. Earlier phases reach it
through the decisions log and the previous phase's notes instead of through their text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PHASE_RE = re.compile(r"(?m)^##\s+(Phase\s+\d+.*?)\s*$")
SECTION_RE = re.compile(r"(?m)^###\s+(.+?)\s*$")
FENCE_RE = re.compile(r"```[a-z]*\n(.*?)```", re.S)


@dataclass
class Phase:
    """One '## Phase N: Title' block of the design."""

    title: str
    body: str
    criteria: list[str] = field(default_factory=list)
    gate: list[str] = field(default_factory=list)

    @property
    def short_title(self):
        """The title without the 'Phase N:' prefix, for the decisions-log heading."""
        return self.title.split(":", 1)[-1].strip()


def parse_phases(text):
    """Split a design document into Phase objects, in document order."""
    parts = PHASE_RE.split(text)
    phases = []
    for i in range(1, len(parts), 2):
        title, body = parts[i].strip(), parts[i + 1].strip()
        sections = SECTION_RE.split(body)
        named = {sections[j].strip().lower(): sections[j + 1] for j in range(1, len(sections), 2)}
        criteria = [ln.strip()[2:].strip() for ln in named.get("exit criteria", "").splitlines()
                    if ln.strip().startswith(("- ", "* "))]
        block = FENCE_RE.search(named.get("gate", ""))
        gate = [ln.strip() for ln in (block.group(1) if block else "").splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        phases.append(Phase(title=title, body=body, criteria=criteria, gate=gate))
    return phases


def preamble(text):
    """Everything before the first phase heading: the material every phase needs."""
    m = PHASE_RE.search(text)
    return (text[:m.start()] if m else text).strip()


def phase_context(text, phases, n):
    """The design excerpt for phase `n`'s prompt: preamble, phase index, that phase in full."""
    index = "\n".join(f"- {p.title}" + ("  <- yours" if i == n else "")
                       for i, p in enumerate(phases, 1))
    phase = phases[n - 1]
    return f"{preamble(text)}\n\n## The phases of this design\n\n{index}\n\n## {phase.title}\n\n{phase.body}"


def validate(phases):
    """Return a list of human-readable problems that make the design unrunnable."""
    problems = [f"Phase {i} has no '### Exit criteria' list."
                for i, p in enumerate(phases, 1) if not p.criteria]
    problems += [f"Phase {i} has no '### Gate' code block."
                 for i, p in enumerate(phases, 1) if not p.gate]
    return problems


def describe(phases):
    """The `styre check` rendering: every phase with its criteria and gate."""
    out = []
    for p in phases:
        out.append(f"\n{p.title}\n  exit criteria:")
        out += [f"    - {c}" for c in p.criteria]
        out.append("  gate:")
        out += [f"    $ {c}" for c in p.gate]
    return "\n".join(out)
