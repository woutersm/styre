from styre.design import parse_phases
from styre.prompts import build_prompt, fix_prompt

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
