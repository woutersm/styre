from styre.design import parse_phases
from styre.prompts import build_prompt, fix_prompt, scope_decisions

PHASE = parse_phases("## Phase 2: Command line interface\n\n### Exit criteria\n- reads stdin\n\n"
                     "### Gate\n```\npytest -q\n```\n")[0]


def test_builder_prompt_states_the_phase_contract():
    text = build_prompt("<the design>", 2, PHASE, "earlier decisions", "notes from phase 1")
    assert "<design>\n<the design>\n</design>" in text
    assert "earlier decisions" in text and "notes from phase 1" in text
    assert "Your phase is: Phase 2: Command line interface" in text
    assert "- reads stdin" in text and "  pytest -q" in text
    assert '## Phase 2: Command line interface"' in text  # decisions-log heading
    assert ".styre/phase2.state.json" in text


def test_builder_prompt_marks_an_empty_history():
    text = build_prompt("d", 1, PHASE, "", "")
    assert "(none yet, this is the first phase)" in text and "(none)" in text


def test_fix_prompt_carries_the_failure_and_the_rules():
    text = fix_prompt(2, PHASE, "Gate command failed: `pytest -q`")
    assert "Gate command failed: `pytest -q`" in text
    assert "do not run git commit" in text
    assert '.styre/phase2.state.json' in text and "fix_rounds_self" in text


DESIGN = ("## Phase 1: Dates (`dates.py`)\n\n### Exit criteria\n- a\n\n### Gate\n```\nx\n```\n"
          "## Phase 2: Tools (`tools.py`)\n\n### Exit criteria\n- b\n\n### Gate\n```\nx\n```\n")

# A real decisions.md in a repo that has already run a different design: that design's
# sections sit above this one's, and used to ship whole in every prompt.
DECISIONS_LOG = """# Decisions

Notes a human left at the top.

## Phase 1: Project setup

An earlier, unrelated design's phase 1.

## Phase 7: SSE parser

Also the earlier design's.

## Phase 1: Dates (`dates.py`)

Chose ZoneInfo over pytz.

## Post-run corrections (2026-09-20, by hand)

Not a phase at all.
"""


def test_only_this_designs_sections_are_sent():
    kept = scope_decisions(DECISIONS_LOG, parse_phases(DESIGN))
    assert "Chose ZoneInfo over pytz." in kept
    assert "An earlier, unrelated design" not in kept    # same number, different title
    assert "SSE parser" not in kept
    assert "Notes a human left at the top." not in kept  # the preamble is not a decision
    assert "Post-run corrections" not in kept            # nor is a hand-written section
    assert kept.startswith("## Phase 1: Dates (`dates.py`)")


def test_a_phase_with_no_decisions_yet_contributes_nothing():
    design = parse_phases(DESIGN)
    assert scope_decisions("", design) == ""
    assert scope_decisions("## Phase 9: Something else\n\nnope\n", design) == ""


def test_the_heading_the_agent_is_told_to_write_is_the_one_that_matches():
    """build_prompt names the heading; scope_decisions matches it. They must not drift."""
    phase = parse_phases(DESIGN)[0]
    told = build_prompt("d", 1, phase, "", "")
    assert f'## Phase 1: {phase.short_title}"' in told
    log = f"## Phase 1: {phase.short_title}\n\nwhat phase 1 decided\n"
    assert "what phase 1 decided" in scope_decisions(log, parse_phases(DESIGN))
