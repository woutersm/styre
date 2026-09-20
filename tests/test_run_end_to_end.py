"""The whole loop, driven by the fake pi on PATH (tests/fake_pi.py)."""
import json
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fixtures' gate uses `test -f`")


def test_happy_path_commits_one_per_phase(styre, repo, commits):
    r = styre("run", "design.md", "--quiet")
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:2] == ["Phase 2: Second phase", "Phase 1: First phase"]
    assert (repo / ".styre" / "report.md").read_text(encoding="utf-8").count(": done,") == 2
    assert (repo / "AGENTS.md").exists()
    assert "## Phase 1" in (repo / "docs" / "decisions.md").read_text(encoding="utf-8")


def test_each_prompt_holds_the_preamble_and_only_its_own_phase(styre, repo, commits):
    styre("run", "design.md", "--quiet")
    one = (repo / ".styre" / "phase1.prompt.md").read_text(encoding="utf-8")
    two = (repo / ".styre" / "phase2.prompt.md").read_text(encoding="utf-8")
    assert "Preamble every phase needs." in one and "Preamble every phase needs." in two
    assert "- Phase 2: Second phase  <- yours" in two   # the index marks the phase at hand
    assert "Do the second thing." in two
    assert "Do the first thing." not in two             # earlier phases arrive as decisions


def test_the_run_branch_is_named_after_the_design(styre, repo, commits):
    styre("run", "design.md", "--quiet")
    head = (repo / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    assert head.endswith("refs/heads/overnight/design")


def test_a_failed_gate_is_fixed_and_then_committed(styre, repo, commits):
    r = styre("run", "design.md", "--quiet",
              plan={"phase1.prompt.md": "bad_gate", "phase1.fix1.md": "ok"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "fix round 1 of 2" in r.stdout
    assert commits()[:2] == ["Phase 2: Second phase", "Phase 1: First phase"]
    assert (repo / ".styre" / "phase1.fix1.md").exists()


def test_a_gate_that_never_goes_green_stops_the_run(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--retries", "1", default="bad_gate")
    assert r.returncode == 1
    assert commits() == ["initial"]
    assert "still failing after 1 fix rounds" in r.stdout


def test_the_test_guard_rejects_a_skip_marker(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--retries", "0", default="skip_test")
    assert r.returncode == 1
    assert "test guard: skipped or removed tests" in r.stdout
    assert commits() == ["initial"]


def test_allow_test_changes_turns_the_guard_off(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--retries", "0", "--allow-test-changes",
              default="skip_test")
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(commits()) == 3


def test_blocked_stops_the_run_with_the_reason(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "blocked"})
    assert r.returncode == 1
    assert "BLOCKED: the design does not say which format to use" in r.stdout
    assert commits() == ["initial"]


def test_done_with_unmet_criteria_is_rejected(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "lying"})
    assert r.returncode == 1
    assert "reported DONE but listed unmet criteria" in r.stdout
    assert "unmet: the second criterion" in (repo / ".styre" / "report.md").read_text(encoding="utf-8")


def test_a_phase_that_changes_nothing_is_not_committed(styre, repo, commits):
    # Phase 1 leaves done.txt committed, so phase 2's gate passes without it touching
    # anything. Phase 1 itself always stages at least AGENTS.md.
    r = styre("run", "design.md", "--quiet", plan={"phase2.prompt.md": "nochange"})
    assert r.returncode == 1
    assert "changed nothing (no staged diff)" in r.stdout
    assert commits()[0] == "Phase 1: First phase"


def test_a_crashing_agent_stops_the_run(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", default="crash")
    assert r.returncode == 1
    assert "pi exited with 3" in r.stdout


def test_a_hung_agent_times_out(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--timeout", "1", default="hang", timeout=90)
    assert r.returncode == 1
    assert "pi exited with 124 (timeout)" in r.stdout


def test_from_phase_resumes_without_rerunning_earlier_phases(styre, repo, commits):
    assert styre("run", "design.md", "--quiet").returncode == 0
    before = commits()
    r = styre("run", "design.md", "--quiet", "--from-phase", "2", "--allow-dirty")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Phase 1: First phase" not in r.stdout
    assert len(commits()) == len(before) + 1


def test_pi_missing_from_path_fails_before_anything_runs(styre, repo, commits):
    r = styre("run", "design.md", path="/nonexistent")
    assert r.returncode == 1
    assert "not found on PATH" in r.stderr
    assert commits() == ["initial"]


def test_a_dirty_tree_is_refused(styre, repo, commits):
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    r = styre("run", "design.md", "--quiet")
    assert r.returncode == 1
    assert "Working tree is not clean" in r.stderr


def test_events_and_log_are_written_separately(styre, repo, commits):
    styre("run", "design.md", "--quiet")
    events = (repo / ".styre" / "logs" / "phase1.events.jsonl").read_text(encoding="utf-8")
    first = json.loads(events.splitlines()[0])
    assert set(first) == {"ts", "line"}
    assert "thinking_delta" in events                      # the raw stream keeps everything
    log = (repo / ".styre" / "logs" / "phase1.log").read_text(encoding="utf-8")
    assert "thinking_delta" not in log                     # the readable log does not
    assert "$ test -f done.txt" in log                     # gate output lands here too
