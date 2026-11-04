"""Acceptance: the docs describe the advisor (M4 phase 5)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ["CLAUDE.md", "docs/architecture.md", "skills/styre/DIRECTOR.md", "skills/styre/SKILL.md", "README.md"]


def read(rel):
    """The document with every run of whitespace made one space, so a rewrapped line still matches."""
    return " ".join((ROOT / rel).read_text(encoding="utf-8").split())


def test_claude_md_lists_the_advisor_module():
    assert "`styre/advisor.py`" in read("CLAUDE.md")


def test_architecture_names_the_advisor_module_and_its_actions():
    text = read("docs/architecture.md")
    assert "`advisor.py`" in text
    assert "amend, split, patch or stop" in text


def test_director_rule_3_reads_the_advice_first_and_keeps_stuck_twice():
    text = read("skills/styre/DIRECTOR.md")
    assert "Where to look" in text
    assert "Stuck twice on the same work" in text


def test_the_skill_names_the_patch_trailer():
    assert "Styre-Advisor: patch" in read("skills/styre/SKILL.md")


def test_readme_no_longer_says_the_advisor_is_not_built():
    assert "The advisor and the reviewer are" not in read("README.md")


def test_no_doc_credits_claude_with_a_commit():
    for rel in DOCS:
        text = read(rel)
        assert "Co-Authored-By" not in text and "Generated with Claude Code" not in text, rel
