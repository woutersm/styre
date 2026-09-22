"""Claude's one turn at a stuck phase, driven by the fake pi and fake claude (--claude-touch)."""
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
    assert not [e for e in timeline(repo) if e["event"].startswith("touch")]


def test_a_touch_that_only_implements_commits_the_phase_as_escalated(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--claude-touch",
              plan={"phase1.prompt.md": "blocked"}, claude_mode="implement")
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:2] == ["Phase 2: Second phase", "Phase 1: First phase"]
    assert "<!-- fake claude patch -->" not in (repo / "design.md").read_text(encoding="utf-8")
    commit_events = [e for e in timeline(repo) if e["event"] == "commit" and e["phase"] == 1]
    assert commit_events[-1]["escalated"] is True
    result = next(e for e in timeline(repo) if e["event"] == "touch_result")
    assert result["patched"] is False and result["cost"] == 0.01
    assert result["is_error"] is False and result["session_id"] == "fake-claude"


def test_a_design_fix_is_committed_apart_from_the_code(styre, repo, commits):
    """A plan change and a code change are different kinds of change, so two commits."""
    r = styre("run", "design.md", "--quiet", "--claude-touch",
              plan={"phase1.prompt.md": "blocked"}, claude_mode="patch")
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:3] == [
        "Phase 2: Second phase", "Phase 1: First phase", "Touch: design fix for phase 1"]
    assert "<!-- fake claude patch -->" in (repo / "design.md").read_text(encoding="utf-8")
    assert next(e for e in timeline(repo) if e["event"] == "touch_result")["patched"] is True
    # The design fix commit carries the design only, not the phase's code.
    fix = [e for e in timeline(repo) if e["event"] == "commit" and e.get("touch")]
    assert len(fix) == 1


def test_a_touch_that_cannot_get_the_gate_green_stops_for_a_human(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--claude-touch",
              plan={"phase1.prompt.md": "blocked"}, claude_mode="fail")
    assert r.returncode == 1
    assert commits() == ["initial"]
    assert "gate is still red" in r.stdout
    kinds = [e["event"] for e in timeline(repo)]
    assert kinds.count("touch_start") == kinds.count("touch_end") == 1


def test_a_second_stop_on_the_same_phase_does_not_touch_again(styre, repo, commits):
    """Resuming the same run after the touch already failed must not spend another one."""
    styre("run", "design.md", "--quiet", "--claude-touch",
          plan={"phase1.prompt.md": "blocked"}, claude_mode="fail")
    run_id = (repo / ".styre" / "latest.txt").read_text(encoding="utf-8").strip()
    r = styre("run", "design.md", "--quiet", "--claude-touch", "--run-id", run_id,
              "--allow-dirty", plan={"phase1.prompt.md": "blocked"}, claude_mode="patch")
    assert r.returncode == 1
    assert commits() == ["initial"]
    assert "already had its Claude touch" in r.stdout
    assert [e["event"] for e in timeline(repo)].count("touch_start") == 1
