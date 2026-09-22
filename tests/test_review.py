import os
import subprocess
import sys
from pathlib import Path

from styre.design import parse_phases
from styre.review import describe_review, find_references

ROOT = Path(__file__).resolve().parent.parent

DESIGN = """# Design

## Phase 1: Touches something old
Rename `WidgetFactory`.

### Exit criteria
- done

### Gate
```
true
```

## Phase 2: Touches nothing
Add a brand new `NeverSeenBefore` module.

### Exit criteria
- done

### Gate
```
true
```
"""


def add_test_file(repo, name, text):
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "add test"], cwd=repo, check=True)


def test_finds_a_hit_in_an_existing_test_file(repo):
    add_test_file(repo, "test_widget.py", "from app import WidgetFactory\n")
    phases = parse_phases(DESIGN)
    refs = find_references(phases, repo_root=repo)
    assert "WidgetFactory" in refs[phases[0].title]
    hit = refs[phases[0].title]["WidgetFactory"][0]
    assert hit.startswith("tests/test_widget.py:1:")


def test_a_brand_new_name_has_no_hits(repo):
    phases = parse_phases(DESIGN)
    refs = find_references(phases, repo_root=repo)
    assert phases[1].title not in refs  # "NeverSeenBefore" exists nowhere yet


def test_a_hit_outside_tests_is_not_reported(repo):
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("class WidgetFactory: ...\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "add src"], cwd=repo, check=True)
    phases = parse_phases(DESIGN)
    refs = find_references(phases, repo_root=repo)
    assert phases[0].title not in refs  # only a src/ hit, no test depends on it yet


def test_builtins_are_excluded_even_when_present_in_tests(repo):
    add_test_file(repo, "test_x.py", "def f(x: str) -> None:\n    return None\n")
    text = "## Phase 1: X\nUses `str` and `None`.\n\n### Exit criteria\n- a\n\n### Gate\n```\ntrue\n```\n"
    phases = parse_phases(text)
    refs = find_references(phases, repo_root=repo)
    assert refs == {}


def test_describe_review_renders_hits_and_the_no_hits_case(repo):
    add_test_file(repo, "test_widget.py", "from app import WidgetFactory\n")
    phases = parse_phases(DESIGN)
    out = describe_review(phases, repo_root=repo)
    assert "Phase 1: Touches something old" in out
    assert "`WidgetFactory` (1)" in out
    assert "tests/test_widget.py:1:" in out
    assert "Phase 2: Touches nothing\n  no existing repo references found" in out


def test_check_cross_references_the_repo_as_well_as_validating(repo):
    """`check` answers one question — is this safe to start tonight — with both halves."""
    add_test_file(repo, "test_widget.py", "from app import WidgetFactory\n")
    (repo / "design.md").write_text(DESIGN, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "design"], cwd=repo, check=True)
    result = subprocess.run(
        [sys.executable, "-m", "styre", "check", "design.md"],
        cwd=repo, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert result.returncode == 0
    assert "exit criteria:" in result.stdout                    # the design, described
    assert "tests/test_widget.py:1:" in result.stdout           # and cross-referenced
    assert "Design looks runnable" in result.stdout


def test_check_skips_the_cross_reference_when_the_design_is_unrunnable(repo):
    """A design that does not parse cannot be run, so greping for its names is noise."""
    add_test_file(repo, "test_widget.py", "from app import WidgetFactory\n")
    (repo / "design.md").write_text("## Phase 1: X\nRename `WidgetFactory`.\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "styre", "check", "design.md"],
        cwd=repo, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert result.returncode == 1
    assert "no '### Exit criteria' list" in result.stdout
    assert "tests/test_widget.py" not in result.stdout
