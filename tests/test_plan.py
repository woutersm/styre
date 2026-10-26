"""`styre plan` (styre/planner.py, the plan subcommand in styre/cli.py, planner_prompt).

No test calls a real model: `fake_claude` stands in for `claude`, installed on `PATH`
before the developer's own `claude`.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import DESIGN  # noqa: E402

from styre import planner

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


def planned_design():
    """The conftest brief with implementation help added, never removing a line."""
    text = DESIGN.replace(
        "Preamble every phase needs.",
        "Preamble every phase needs.\nThe repo's tests run with `uv run pytest -q`.")
    text = text.replace("Do the first thing.", "Do the first thing.\nA copied-from note.")
    text = text.replace("Do the second thing.", "Do the second thing.\nA copied-from note.")
    return text


def run_plan(repo, fake_claude, tmp_path, monkeypatch, reply=None, reply_dir=None,
             exit_code=None, cwd=None):
    """Run `python -m styre plan` in the repo with fake_claude on PATH. Returns (rc, out, err)."""
    cfg = tmp_path / "styre.json"
    cfg.write_text('{"frontier": {"command": ["claude"], "timeout": 60}}', encoding="utf-8")
    env = dict(os.environ)
    env["STYRE_CONFIG"] = str(cfg)
    env["PATH"] = fake_claude
    env["PYTHONPATH"] = str(ROOT)
    env["FAKE_CLAUDE_LOG"] = str(tmp_path / "fake_claude.log")
    for var in ("FAKE_CLAUDE_REPLY", "FAKE_CLAUDE_EXIT", "FAKE_CLAUDE_SLEEP",
                "FAKE_PI_PLAN", "FAKE_PI_DEFAULT"):
        env.pop(var, None)
    if reply is not None:
        env["FAKE_CLAUDE_REPLY"] = str(reply)
    if reply_dir is not None:
        env["FAKE_CLAUDE_REPLY"] = str(reply_dir)
    if exit_code is not None:
        env["FAKE_CLAUDE_EXIT"] = str(exit_code)
    p = subprocess.run([sys.executable, "-m", "styre", "plan", "design.md"],
                       cwd=cwd or repo, env=env, capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


def call_stdins(log_path):
    lines = Path(log_path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def git(*args, cwd):
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return out.stdout


@pytest.fixture
def plan_repo(tmp_path, monkeypatch, fake_claude):
    """A lean git repository holding design.md, isolated from the developer's repository."""
    # The fake repo lives under the real checkout; keep git from climbing to the real one.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    exclude = path / ".git" / "info" / "exclude"
    exclude.write_text(".styre/\n__pycache__/\n*.pyc\n", encoding="utf-8")
    (path / "README.md").write_text("start\n", encoding="utf-8")
    (path / "design.md").write_text(DESIGN, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)
    return path


def test_good_answer_commits_the_planned_design(tmp_path, monkeypatch, fake_claude, plan_repo):
    reply = tmp_path / "planned.json"
    reply.write_text(json.dumps(
        {"type": "result", "is_error": False, "structured_output": {"design": planned_design()}}),
        encoding="utf-8")
    rc, out, err = run_plan(plan_repo, fake_claude, tmp_path, monkeypatch, reply=str(reply))
    assert rc == 0, err
    assert "design.md" in out
    assert "tokens" in out
    subjects = git("log", "--format=%s", cwd=plan_repo).splitlines()
    assert subjects[0] == "Plan: design"
    assert git("show", "--name-only", "--format=", cwd=plan_repo).splitlines() == ["design.md"]
    assert not git("status", "--porcelain", cwd=plan_repo).strip()  # the tree stays clean
    assert (plan_repo / "design.md").read_text(encoding="utf-8") == planned_design()
    runs = sorted((plan_repo / ".styre" / "runs").iterdir())
    timeline = (runs[0] / "timeline.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in timeline.splitlines()]
    assert [e["event"] for e in events].count("model_call") == 1
    assert events[0]["event"] == "run_start" and events[0]["kind"] == "plan"
    assert events[-1]["event"] == "run_end" and events[-1]["stopped"] is None


def test_bad_first_answer_gets_one_retry_then_fails(tmp_path, monkeypatch, fake_claude, plan_repo):
    bad = DESIGN.replace("Preamble every phase needs.", "something else entirely")
    assert (plan_repo / "design.md").read_text(encoding="utf-8") == DESIGN  # the tree holds the brief
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "1.json").write_text(json.dumps(
        {"type": "result", "is_error": False, "structured_output": {"design": bad}}), encoding="utf-8")
    (replies / "2.json").write_text(json.dumps(
        {"type": "result", "is_error": False,
         "structured_output": {"design": planned_design()}}),
        encoding="utf-8")
    rc, out, err = run_plan(plan_repo, fake_claude, tmp_path, monkeypatch, reply_dir=replies)
    assert rc == 0, err
    stdins = call_stdins(tmp_path / "fake_claude.log")
    assert len(stdins) == 2  # one retry
    assert "Your design was refused:" in stdins[1]["stdin"]
    assert stdins[0]["stdin"] in stdins[1]["stdin"]  # the first prompt, plus the problems
    assert "dropped the brief's line" in stdins[1]["stdin"]


def test_second_bad_answer_fails_cleanly(tmp_path, monkeypatch, fake_claude, plan_repo):
    bad = DESIGN.replace("Preamble every phase needs.", "something else entirely")
    replies = tmp_path / "replies"
    replies.mkdir()
    for n in ("1", "2"):
        (replies / f"{n}.json").write_text(json.dumps(
            {"type": "result", "is_error": False, "structured_output": {"design": bad}}),
            encoding="utf-8")
    before = git("rev-parse", "HEAD", cwd=plan_repo)
    rc, out, err = run_plan(plan_repo, fake_claude, tmp_path, monkeypatch, reply_dir=replies)
    assert rc == 1
    assert "dropped the brief's line" in out
    assert "Traceback" not in err
    assert (plan_repo / "design.md").read_text(encoding="utf-8") == DESIGN  # brief untouched
    assert git("rev-parse", "HEAD", cwd=plan_repo) == before  # no commit
    assert not git("status", "--porcelain", cwd=plan_repo).strip()
    runs = sorted((plan_repo / ".styre" / "runs").iterdir())
    timeline = (runs[0] / "timeline.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in timeline.splitlines()]
    end = events[-1]
    assert end["event"] == "run_end"
    assert end["stopped"] is not None and "dropped the brief's line" in end["stopped"]


def test_planner_call_error_stops_with_its_sentence(tmp_path, monkeypatch, fake_claude, plan_repo):
    rc, out, err = run_plan(plan_repo, fake_claude, tmp_path, monkeypatch,
                            reply=str(FIXTURES / "claude_error_budget.json"), exit_code=1)
    assert rc == 1
    assert "Reached maximum budget" in err
    assert "Traceback" not in err
    assert (plan_repo / "design.md").read_text(encoding="utf-8") == DESIGN
    assert git("log", "--format=%s", cwd=plan_repo).splitlines() == ["initial"]
    assert not git("status", "--porcelain", cwd=plan_repo).strip()
    runs = sorted((plan_repo / ".styre" / "runs").iterdir())
    timeline = (runs[0] / "timeline.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in timeline.splitlines()]
    end = events[-1]
    assert end["event"] == "run_end"
    assert end["stopped"] is not None and "Reached maximum budget" in end["stopped"]


def test_retry_prompt_after_a_gate_change(tmp_path, monkeypatch, fake_claude, plan_repo):
    brief = (plan_repo / "design.md").read_text(encoding="utf-8")  # the conftest brief
    changed = brief.replace("done.txt still exists\n\n### Gate\n```\ntest -f done.txt\n```",
                            "done.txt still exists\n\n### Gate\n```\ntest -f other.txt\n```")
    assert changed != brief  # the replace really hit Phase 2's gate
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "1.json").write_text(json.dumps(
        {"type": "result", "is_error": False, "structured_output": {"design": changed}}),
        encoding="utf-8")
    (replies / "2.json").write_text(json.dumps(
        {"type": "result", "is_error": False, "structured_output": {"design": planned_design()}}),
        encoding="utf-8")
    rc, out, err = run_plan(plan_repo, fake_claude, tmp_path, monkeypatch, reply_dir=replies)
    assert rc == 0, err
    stdins = call_stdins(tmp_path / "fake_claude.log")
    assert "Phase 2 changed the brief's gate" in stdins[1]["stdin"]


# --- planner.problems, one test per rule ----------------------------------------


def test_problems_is_empty_when_only_lines_are_added():
    assert planner.problems(DESIGN, planned_design()) == []


def test_problems_names_a_missing_line_and_gate():
    dropped = planned_design().replace("- done.txt exists\n", "")
    changed_gate = planned_design().replace("test -f done.txt\n```", "test -f other.txt\n```")
    assert any("Phase 1 dropped the brief's line" in p and "- done.txt exists" in p
               for p in planner.problems(DESIGN, dropped))
    assert any("Phase 2 changed the brief's gate" in p
               for p in planner.problems(DESIGN, changed_gate))


def test_problems_names_missing_or_renamed_phases():
    two = DESIGN.split("## Phase 2")[0]
    assert any("1 phase where the brief has 2" in p
               for p in planner.problems(DESIGN, two))
    renamed = planned_design().replace("## Phase 2: Second phase", "## Phase 2: Renamed")
    assert any("Phase 2's title changed" in p for p in planner.problems(DESIGN, renamed))


def test_problems_names_a_new_advisory():
    advisory = planned_design().replace(
        "Preamble every phase needs.",
        "Preamble every phase needs.\nRead `docs/agent-design.md` first; it explains the API.")
    assert any("new advisory" in p and "agent-design.md" in p
               for p in planner.problems(DESIGN, advisory))


def test_problems_names_an_overlong_phase_prompt():
    big = planned_design().replace("Do the first thing.", "Do the first thing.\n" + "x" * 41000)
    assert any("over the 40,000 limit" in p for p in planner.problems(DESIGN, big))


def test_problems_names_an_invalid_planned_design():
    # Removing phase 2's gate leaves a design `validate` cannot run.
    no_gate = planned_design().split("### Exit criteria\n- done.txt still exists")[0]
    assert any("Phase 2 has no '### Gate'" in p for p in planner.problems(DESIGN, no_gate))


# --- planner_prompt --------------------------------------------------------------


def test_planner_prompt_states_the_contract_and_holds_the_brief():
    from styre.prompts import planner_prompt
    text = planner_prompt(DESIGN, 128000)
    assert "a context of 128,000 tokens" in text
    assert "You are preparing a design for an unattended build" in text
    assert "every line of the brief" in text
    assert "`design` field." in text
    assert "<brief>" in text and text.index("<brief>") > text.index("`design` field.")
    assert text.split("<brief>")[1].lstrip().startswith(DESIGN)  # the brief, verbatim, at the end


def test_planner_prompt_leaves_out_the_size_without_a_window():
    from styre.prompts import planner_prompt
    text = planner_prompt(DESIGN, None)
    assert "a context of" not in text  # the sentence leaves out the size entirely
    assert "no web access" in text


def test_dirty_tree_is_refused_before_any_call(tmp_path, monkeypatch, fake_claude, plan_repo):
    (plan_repo / "stray.md").write_text("x\n", encoding="utf-8")
    assert git("status", "--porcelain", cwd=plan_repo).strip()  # the tree really is dirty
    rc, out, err = run_plan(plan_repo, fake_claude, tmp_path, monkeypatch)
    assert rc != 0
    assert "not clean" in err
    assert not (tmp_path / "fake_claude.log").exists()  # no model call was made


def test_subdirectory_is_refused_before_any_call(tmp_path, monkeypatch, fake_claude, plan_repo):
    sub = plan_repo / "sub"
    sub.mkdir()
    rc, out, err = run_plan(plan_repo, fake_claude, tmp_path, monkeypatch, cwd=sub)
    assert rc == 1
    assert "repository root" in err
    assert not (tmp_path / "fake_claude.log").exists()  # no model call was made
