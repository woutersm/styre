from styre.design import parse_phases
from styre.prompts import build_prompt, fix_prompt

PHASE = parse_phases("## Phase 2: Command line interface\n\n### Exit criteria\n- reads stdin\n\n"
                     "### Gate\n```\npytest -q\n```\n")[0]


def test_builder_prompt_states_the_phase_contract():
    text = build_prompt("<the design>", 2, PHASE, "notes from phase 1")
    assert "<design>\n<the design>\n</design>" in text
    assert "notes from phase 1" in text
    assert "Your phase is: Phase 2: Command line interface" in text
    assert "- reads stdin" in text and "  pytest -q" in text
    assert '## Phase 2: Command line interface"' in text  # decisions-log heading
    assert ".styre/phase2.state.json" in text


def test_builder_prompt_marks_an_empty_history():
    assert "(none)" in build_prompt("d", 1, PHASE, "")


def test_the_decisions_log_is_written_but_never_read_back():
    """styre's first rule is that the agent's account of its own work is not trusted. The
    decisions log was the one thing forwarded to the next agent as fact, ungated."""
    text = build_prompt("<the design>", 2, PHASE, "notes from phase 1")
    assert "decisions_from_earlier_phases" not in text
    assert "docs/decisions.md, appending" in text      # still written, for humans


def test_fix_prompt_carries_the_failure_and_the_rules():
    text = fix_prompt(2, PHASE, "Gate command failed: `pytest -q`")
    assert "Gate command failed: `pytest -q`" in text
    assert "do not run git commit" in text
    assert '.styre/phase2.state.json' in text and "fix_rounds_self" in text
