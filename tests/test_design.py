from pathlib import Path

from styre.design import describe, parse_phases, phase_context, preamble, validate

EXAMPLE = Path(__file__).resolve().parent.parent / "example-design.md"


def test_parses_the_example_design():
    phases = parse_phases(EXAMPLE.read_text(encoding="utf-8"))
    assert [p.title for p in phases] == [
        "Phase 1: Project setup and core counting library",
        "Phase 2: Command line interface",
    ]
    assert phases[0].gate == ["uv sync --locked", "uv run ruff check .", "uv run pytest -q"]
    assert len(phases[0].criteria) == 6
    assert phases[0].short_title == "Project setup and core counting library"
    assert validate(phases) == []


def test_preamble_is_not_a_phase():
    assert parse_phases("# Title\n\nSome preamble.\n\n## Not a phase\ntext\n") == []


def test_gate_drops_comments_and_blank_lines():
    phases = parse_phases("## Phase 1: X\n\n### Exit criteria\n- a\n\n### Gate\n```sh\n"
                          "# a comment\n\n  pytest -q  \n```\n")
    assert phases[0].gate == ["pytest -q"]


def test_criteria_accept_both_bullet_markers():
    phases = parse_phases("## Phase 1: X\n\n### Exit criteria\n- a\n* b\nnot a bullet\n\n"
                          "### Gate\n```\ntrue\n```\n")
    assert phases[0].criteria == ["a", "b"]


def test_validate_names_the_missing_parts():
    phases = parse_phases("## Phase 1: X\nbody\n\n## Phase 2: Y\n\n### Exit criteria\n- a\n")
    assert validate(phases) == [
        "Phase 1 has no '### Exit criteria' list.",
        "Phase 1 has no '### Gate' code block.",
        "Phase 2 has no '### Gate' code block.",
    ]


def test_describe_shows_criteria_and_gate():
    text = describe(parse_phases(EXAMPLE.read_text(encoding="utf-8")))
    assert "Phase 2: Command line interface" in text
    assert "    $ uv run ruff check ." in text


TWO = ("# Plan\n\nRead the design first.\n\n"
       "## Phase 1: X\n\nbuild x\n\n### Exit criteria\n- a\n\n### Gate\n```\ntrue\n```\n\n"
       "## Phase 2: Y\n\nbuild y\n\n### Exit criteria\n- b\n\n### Gate\n```\ntrue\n```\n")


def test_preamble_stops_at_the_first_phase():
    assert preamble(TWO) == "# Plan\n\nRead the design first."
    assert preamble("no phases here") == "no phases here"


def test_phase_context_carries_the_preamble_its_phase_and_an_index():
    phases = parse_phases(TWO)
    text = phase_context(TWO, phases, 2)
    assert "Read the design first." in text                 # preamble, every phase gets it
    assert "- Phase 1: X\n- Phase 2: Y  <- yours" in text   # index, with this phase marked
    assert "## Phase 2: Y\n\nbuild y" in text               # its own section, in full
    assert "build x" not in text                            # not the other phases' bodies
