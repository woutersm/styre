"""The ladder, driven by the fake pi and the fake claude on PATH (--claude-touch)."""
import json
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fixtures' gate uses `test -f`")


def run_dir(repo):
    name = (repo / ".styre" / "latest.txt").read_text(encoding="utf-8").strip()
    return repo / ".styre" / "runs" / name


def timeline(repo):
    text = (run_dir(repo) / "timeline.jsonl").read_text(encoding="utf-8")
    return [json.loads(ln) for ln in text.splitlines()]


def test_without_the_flag_a_stop_behaves_exactly_as_before(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "blocked"})
    assert r.returncode == 1
    assert commits() == ["initial"]
    assert not (run_dir(repo) / "touches.json").exists()


def test_touch1_patches_the_design_and_the_retry_succeeds(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--claude-touch",
             plan={"phase1.prompt.md": "blocked_then_ok"}, claude_mode="patch")
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:3] == [
        "Phase 2: Second phase", "Phase 1: First phase", "Touch 1: design fix for phase 1"]
    assert "<!-- fake claude patch -->" in (repo / "design.md").read_text(encoding="utf-8")
    assert json.loads((run_dir(repo) / "touches.json").read_text(encoding="utf-8")) == {"1": 1}
    events = [e for e in timeline(repo) if e["event"] == "touch1_result"]
    assert events == [{**events[0], "phase": 1, "patched": True, "is_error": False,
                       "cost": 0.01, "session_id": "fake-claude"}]


def test_touch1_declines_and_touch2_executes_the_phase(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--claude-touch",
             plan={"phase1.prompt.md": "blocked"}, claude_mode="decline")
    assert r.returncode == 0, r.stdout + r.stderr
    subjects = commits()
    assert subjects[0] == "Phase 2: Second phase"
    assert subjects[1] == "Phase 1: First phase"
    assert json.loads((run_dir(repo) / "touches.json").read_text(encoding="utf-8")) == {"1": 2}
    commit_events = [e for e in timeline(repo) if e["event"] == "commit" and e["phase"] == 1]
    assert commit_events[-1]["escalated"] is True
    kinds = [e["event"] for e in timeline(repo)]
    assert "touch1_result" in kinds and "touch2_start" in kinds and "touch2_end" in kinds


def test_touch2_also_failing_stops_for_a_human(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--claude-touch",
             plan={"phase1.prompt.md": "blocked"}, claude_mode="decline_fail")
    assert r.returncode == 1
    assert commits() == ["initial"]
    assert json.loads((run_dir(repo) / "touches.json").read_text(encoding="utf-8")) == {"1": 2}
    assert "gate is still red" in r.stdout or "gate is still red" in r.stderr


def test_a_third_stop_on_the_same_phase_does_not_touch_again(styre, repo, commits):
    """Resuming the same run after Touch 2 already failed must not spend a third touch."""
    styre("run", "design.md", "--quiet", "--claude-touch",
         plan={"phase1.prompt.md": "blocked"}, claude_mode="decline_fail")
    run_id = (repo / ".styre" / "latest.txt").read_text(encoding="utf-8").strip()
    r = styre("run", "design.md", "--quiet", "--claude-touch", "--run-id", run_id,
             "--allow-dirty", plan={"phase1.prompt.md": "blocked"}, claude_mode="patch")
    assert r.returncode == 1
    assert commits() == ["initial"]
    assert "already spent" in r.stdout
    assert json.loads((run_dir(repo) / "touches.json").read_text(encoding="utf-8")) == {"1": 2}
