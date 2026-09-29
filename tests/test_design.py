from pathlib import Path

from styre.design import (
    advisories,
    describe,
    doc_references,
    parse_phases,
    phase_context,
    preamble,
    skip_requests,
    validate,
)

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


GATE = "\n\n### Exit criteria\n- a\n\n### Gate\n```\ntrue\n```\n"


def design(preamble="", body="Body.", criteria=1):
    crit = "".join(f"- criterion {i}\n" for i in range(criteria))
    return (f"{preamble}\n\n## Phase 1: X\n{body}\n\n### Exit criteria\n{crit}\n"
            "### Gate\n```\ntrue\n```\n")


def test_a_preamble_that_says_read_a_document_is_flagged():
    """The line that cost two days: one 2.3 KB phase became a 44 KB context, the model
    returned nothing, and styre reported "no state file written"."""
    text = design('**"The design" means `docs/agent-design.md`.** Read it first.')
    assert doc_references(preamble(text)) == ["docs/agent-design.md"]
    notes = advisories(text, parse_phases(text), [1000])
    assert any("docs/agent-design.md" in n and "unbounded prompt" in n for n in notes)


def test_naming_a_document_without_telling_the_agent_to_read_it_is_fine():
    """Designs cross-reference other plans constantly. Only a reading instruction counts —
    without this the check reported 7 documents on a real design where 1 mattered."""
    text = design("This plan runs before `event-sources-todo.md`. Its Phase 8 adds two.")
    assert doc_references(preamble(text)) == []


def test_a_design_that_forbids_the_read_is_not_warned_about_it():
    """Warning about the fix would teach the reader to ignore the warning."""
    text = design("**Do not open anything in `docs/`** — not `agent-design.md`.")
    assert doc_references(preamble(text)) == []


def test_the_designs_own_filename_and_the_contract_files_are_not_flagged():
    text = design("Read `plan.md` and append to `docs/decisions.md`; see `AGENTS.md`.")
    assert doc_references(preamble(text), design_path="docs/plan.md") == []


def test_an_outsized_phase_is_flagged_by_prompt_size_or_criteria_count():
    text = design(criteria=9)
    phases = parse_phases(text)
    assert any("9 exit criteria" in n for n in advisories(text, phases, [1000]))
    # and by size against its neighbours
    two = parse_phases(design(criteria=1) + "\n## Phase 2: Y\nb\n\n### Exit criteria\n- a\n\n"
                       "### Gate\n```\ntrue\n```\n")
    notes = advisories("x", two, [1000, 9000])
    assert any("Phase 2 is large" in n and "9.0x the median" in n for n in notes)


def test_a_phase_that_asks_for_a_skipped_test_is_flagged():
    """The real collision, app phase 12 on 2026-09-23: the design said to skip on
    non-macOS, the agent did, and the test guard rejected the phase for it."""
    text = design(body="`app-launchd.sh --dry-run` exits 0; skip on non-macOS as\n"
                       "`tests/test_scripts.py` already does.")
    assert "skip on non-macOS" in skip_requests(parse_phases(text)[0].body)
    notes = advisories(text, parse_phases(text), [1000])
    assert any("Phase 1 asks for a skipped test" in n and "test guard rejects" in n
               for n in notes)


def test_a_design_that_forbids_skipping_is_not_warned_about_it():
    """Same rule as the reading-verb negation: warning about the design agreeing with the
    guard would teach the reader to ignore the warning."""
    assert skip_requests("Never skip on any platform: the whole suite runs.") is None


def test_skip_outside_a_test_context_is_not_a_skipped_test():
    """A directive still has to be about tests."""
    assert skip_requests("The poller will skip on a retryable error and try again.") is None


def test_a_subject_that_skips_is_not_a_skipped_test():
    """Measured on app's phase 5, which the loose version flagged: "skipping" here is the
    behaviour under test, and a warning that cries wolf is one the reader learns to skim."""
    assert skip_requests("31 January → 28 February. This is the regression test for "
                         "`rrule`'s skipping behaviour.") is None


def test_a_clean_design_gets_no_advisories():
    text = design("A short preamble every phase needs.")
    assert advisories(text, parse_phases(text), [1000]) == []


def test_phases_gated_in_two_toolchains_are_named_once():
    """Measured on app (2026-09-29): 6 of the 7 phases gated in the root and in `cd ui` peaked
    at 74-116k. Every UI phase there is one, so they are named in a single note."""
    from styre.design import advisories, parse_phases, toolchains
    def phase(n, gate):
        return f"## Phase {n}: P{n}\nWork.\n### Exit criteria\n- it works\n### Gate\n```\n{gate}\n```\n"
    text = (phase(1, "uv run pytest -q") + phase(2, "uv run pytest -q\ncd ui && npm run test")
            + phase(3, "cd ui/ && npm run build\nuv run mypy src"))
    phases = parse_phases(text)
    assert [toolchains(p) for p in phases] == [["."], [".", "ui"], [".", "ui"]]
    notes = [n for n in advisories(text, phases, [1000] * 3) if "toolchain" in n]
    assert len(notes) == 1 and notes[0].startswith("Phase(s) 2, 3 are gated")


def test_a_new_library_without_an_example_is_flagged(tmp_path):
    """app sources phase 3 (2026-09-28): the design named `icalendar` as a dependency and
    gave no example of it, and each of four steps spent ~12 `python -c` calls learning its API."""
    from styre.design import advisories, parse_phases
    (tmp_path / "pyproject.toml").write_text('dependencies = ["httpx>=0.27"]\n')
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "package.json").write_text('{"dependencies": {"react": "19"}}')
    pre = "| Dependencies | `icalendar`, `recurring-ical-events`; the rest is `httpx` |\n\n"
    bare = ("## Phase 1: Calendar\nExpand with `recurring_ical_events.of(cal).between(a, b)`, "
            "parse with `icalendar.Calendar.from_ical`, fetch with `httpx`.\n"
            "### Exit criteria\n- it works\n### Gate\n```\npytest\n```\n")
    shown = ("## Phase 2: Calendar again\nUse `icalendar`:\n```python\n"
             "from icalendar import Calendar\ncal = Calendar.from_ical(data)\n```\n"
             "### Exit criteria\n- it works\n### Gate\n```\npytest\n```\n")
    later = ("## Phase 3: Chart\nRun `npm install recharts`, then draw it with `recharts`.\n"
             "### Exit criteria\n- it works\n### Gate\n```\npytest\n```\n")
    text = pre + bare + shown + later
    notes = [n for n in advisories(text, parse_phases(text), [1000] * 3, root=tmp_path)
             if "does not depend" in n]
    assert [n.split(", which")[0] for n in notes] == [
        "Phase 1 uses `icalendar`, `recurring-ical-events`",  # httpx is installed; phase 2 shows it
        "Phase 3 uses `recharts`"]
    assert advisories(text, parse_phases(text), [1000] * 3) == [n for n in advisories(
        text, parse_phases(text), [1000] * 3) if "does not depend" not in n]  # no root: skipped

