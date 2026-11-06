"""`styre plan`: the check that keeps the brief's contract intact.

`claude.call` returns the whole planned design as text. The planner is told to add lines and
never edit or remove them, but the model is not the gate: `problems()` re-parses the answer
and says, one sentence each, every line of the brief that is missing, every gate, criteria
list, title or phase count that changed, and every phase whose prompt grew past the budget.
Empty means the planned design may replace the brief. A warning the planner added is not a
problem: `styre plan` prints it for the person who approves the plan. Refusing on warnings
threw away three finished heim-mcp plans on 2026-11-01.
"""
from __future__ import annotations

from styre.design import parse_phases, phase_context, preamble, validate
from styre.guard import SKIP_RE

PLAN_SCHEMA = {"type": "object", "properties": {"design": {"type": "string"}},
               "required": ["design"], "additionalProperties": False}

MAX_PHASE_PROMPT = 40_000


def _lines(text):
    """The document's stripped, non-blank lines, in order."""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _dropped(brief_lines, planned_lines):
    """The brief's lines absent from the planned ones, in order (duplicates kept once)."""
    have = set(planned_lines)
    seen, out = set(), []
    for ln in brief_lines:
        if ln not in have and ln not in seen:
            seen.add(ln)
            out.append(ln)
    return out


def problems(brief, planned):
    """One sentence per rule the planned design broke; empty when it is good."""
    out = []
    bph, pph = parse_phases(brief), parse_phases(planned)
    out += validate(pph)
    if len(bph) != len(pph):
        out.append(f"The planned design has {len(pph)} phase where the brief has {len(bph)}.")
        return out  # the phases no longer line up; the per-phase checks below cannot

    # Additive only, per the design: every non-blank line of the brief's preamble must appear
    # in the planned preamble, and every non-blank line of brief phase n in planned phase n
    # (a phase's body covers its own text, criteria and gate).
    for ln in _dropped(_lines(preamble(brief)), _lines(preamble(planned))):
        out.append(f"The planned design's preamble dropped the brief's line: `{ln}`.")
    for i, (b, p) in enumerate(zip(bph, pph), 1):
        if b.title != p.title:
            out.append(f"Phase {i}'s title changed from '{b.title}' to '{p.title}'.")
        for ln in _dropped(_lines(b.body), _lines(p.body)):
            out.append(f"Phase {i} dropped the brief's line: `{ln}`.")
    for i, (b, p) in enumerate(zip(bph, pph), 1):
        if b.gate != p.gate:
            out.append(f"Phase {i} changed the brief's gate: {b.gate} became {p.gate}.")
        if b.criteria != p.criteria:
            out.append(f"Phase {i} changed the brief's exit criteria: "
                       f"{b.criteria} became {p.criteria}.")

    # A skip marker in an acceptance file is one the test guard rejects when styre stages the
    # file, and the builder cannot remove it: styre writes the file back before every gate.
    # The M4 plan (2026-11-03) put a Windows skipif in three of them.
    for i, p in enumerate(pph, 1):
        for path, content in p.acceptance:
            if content and SKIP_RE.search(content):
                out.append(f"Phase {i}'s acceptance test '{path}' has a skip or xfail marker, "
                           "which styre's test guard rejects.")

    for i in range(1, len(pph) + 1):
        size = len(phase_context(planned, pph, i))
        if size > MAX_PHASE_PROMPT:
            out.append(f"Phase {i}'s prompt is {size:,} characters, "
                       f"over the {MAX_PHASE_PROMPT:,} limit.")
    return out
