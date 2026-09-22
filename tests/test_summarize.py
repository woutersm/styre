"""The summarize readers, against the captured pi output in tests/fixtures/."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from styre.rundir import RunDir
from styre.summarize import Usage, collect, read_events, render, summarize

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def events_file(path, source, seconds=1):
    """Wrap a captured pi stream the way stream_pi() writes it: one arrival stamp per line."""
    ts = datetime(2026, 9, 20, 22, 0, 0).astimezone()
    with open(path, "w", encoding="utf-8") as f:
        for i, line in enumerate(source.read_text(encoding="utf-8").splitlines()):
            f.write(json.dumps({"ts": (ts + timedelta(seconds=i * seconds)).isoformat(),
                                "line": line}) + "\n")


def make_run(tmp_path, timeline=(), states=(), fixture="pi_toolcall.jsonl", phases=(1,)):
    run = RunDir(tmp_path / "20260920-220000")
    (run.root / "logs").mkdir(parents=True)
    if timeline:
        run.timeline.write_text("".join(json.dumps(e) + "\n" for e in timeline), encoding="utf-8")
    for n in phases:
        events_file(run.events(n), FIXTURES / fixture)
    for n, state in states:
        run.state(n).write_text(json.dumps(state), encoding="utf-8")
    return run


def test_read_events_unwraps_pis_event_from_our_wrapper(tmp_path):
    events_file(tmp_path / "e.jsonl", FIXTURES / "pi_simple.jsonl")
    events = list(read_events(tmp_path / "e.jsonl"))
    assert events and events[0]["type"] == "session"


def test_read_events_skips_lines_that_are_not_events(tmp_path):
    path = tmp_path / "e.jsonl"
    path.write_text('{"ts": "2026-09-20T22:00:00+02:00", "line": "pi: something went wrong"}\n'
                    '{"ts": "2026-09-20T22:00:01+02:00", "line": "{\\"type\\": \\"agent_end\\"}"}\n'
                    'not json at all\n', encoding="utf-8")
    assert [e["type"] for e in read_events(path)] == ["agent_end"]


def test_a_clean_tool_call_produces_no_noise(tmp_path):
    # Only failures are counted: a phase whose tools all worked has nothing to report.
    assert collect(make_run(tmp_path)).phases[0].tool_errors == {}


def test_a_failed_tool_call_is_counted_and_reported(tmp_path):
    run = RunDir(tmp_path / "run")
    (run.root / "logs").mkdir(parents=True)
    run.events(1).write_text(
        '{"ts": "2026-09-20T22:00:00+02:00", "line": '
        '"{\\"type\\": \\"tool_execution_end\\", \\"toolName\\": \\"bash\\", '
        '\\"isError\\": true}"}\n', encoding="utf-8")
    summary = collect(run)
    assert summary.phases[0].tool_errors == {"bash": 1}
    assert "1 failed bash call(s)" in render(summary)


def test_the_captured_fixtures_have_zero_usage_and_that_is_read_as_zero(tmp_path):
    # These were captured before the provider was fixed to report usage. A parser must read
    # them as zeros, not conclude that counts are always zero.
    phase = collect(make_run(tmp_path)).phases[0]
    assert phase.usage.input == 0 and phase.usage.output == 0


def test_real_token_counts_are_read_off_a_post_fix_capture(tmp_path):
    # pi_usage.jsonl was captured after the mlxserve provider was set to report usage while
    # streaming, so unlike the older fixtures it carries real numbers.
    usage = collect(make_run(tmp_path, fixture="pi_usage.jsonl")).phases[0].usage
    assert (usage.input, usage.output, usage.cache_read) == (1560, 23, 6144)
    assert usage.reasoning == 0                           # reported as zero, not absent


def test_usage_takes_the_last_input_and_sums_the_output():
    u = Usage()
    u.add({"input": None, "output": None})                       # the first message_end
    u.add({"input": 1507, "output": 34, "cacheRead": 6144, "totalTokens": 7685})
    u.add({"input": 2200, "output": 50, "cacheRead": 1000})
    assert (u.input, u.output, u.cache_read) == (2200, 84, 7144)


def test_thinking_is_not_reported_as_zero_when_the_provider_omits_it():
    u = Usage()
    u.add({"input": 10, "output": 40})
    assert u.reasoning is None                            # absent, which is not zero
    u.add({"input": 20, "output": 60, "reasoning": 45})
    assert u.reasoning == 45


TIMELINE = [
    {"ts": "2026-09-20T22:00:00+02:00", "event": "run_start", "run": "20260920-220000",
     "design": "d.md", "branch": "overnight/d", "pi_version": "0.85.1", "styre": "0.1.0",
     "design_sha256": "abc123", "templates": "def456", "phases": 2, "from_phase": 1},
    {"ts": "2026-09-20T22:00:01+02:00", "event": "pi_end", "phase": 1, "step": "builder",
     "seconds": 600.0, "rc": 0},
    {"ts": "2026-09-20T22:10:00+02:00", "event": "gate_end", "phase": 1, "step": "builder",
     "command": "pytest -q", "seconds": 30.0, "rc": 1},
    {"ts": "2026-09-20T22:10:30+02:00", "event": "pi_end", "phase": 1, "step": "fix 1",
     "seconds": 300.0, "rc": 0},
    {"ts": "2026-09-20T22:15:30+02:00", "event": "gate_end", "phase": 1, "step": "fix 1",
     "command": "pytest -q", "seconds": 20.0, "rc": 0},
    {"ts": "2026-09-20T22:15:50+02:00", "event": "guard_result", "phase": 1, "step": "fix 1",
     "ok": True, "problem": None},
    {"ts": "2026-09-20T22:15:51+02:00", "event": "commit", "phase": 1, "sha": "a" * 40,
     "subject": "Phase 1: One"},
    {"ts": "2026-09-20T22:15:52+02:00", "event": "phase_end", "phase": 1,
     "title": "Phase 1: One", "status": "committed", "reason": None, "rounds": 1,
     "fix_rounds_self": 3, "unmet_criteria": []},
    {"ts": "2026-09-20T22:16:00+02:00", "event": "run_end", "exit_code": 0, "committed": 1,
     "stopped": None},
]


def test_the_timeline_drives_the_phase_table(tmp_path):
    summary = collect(make_run(tmp_path, timeline=TIMELINE))
    phase = summary.phases[0]
    assert phase.title == "Phase 1: One" and phase.status == "committed"
    assert (phase.agent_seconds, phase.gate_seconds) == (900.0, 50.0)
    assert phase.rounds == 1 and phase.self_rounds == 3
    assert phase.failed_gates == [("builder", "pytest -q", 1)]
    assert phase.sha == "a" * 40
    text = render(summary)
    assert "| 1 | Phase 1: One | committed | aaaaaaa | 15.0      | 0.8" in text
    assert "0.85.1" in text and "overnight/d" in text and "templates def456" in text


def test_self_corrected_rounds_without_visible_ones_are_called_out(tmp_path):
    timeline = [e for e in TIMELINE if e["event"] not in ("gate_end", "pi_end")]
    timeline = [{**e, "rounds": 0} if e["event"] == "phase_end" else e for e in timeline]
    text = render(collect(make_run(tmp_path, timeline=timeline)))
    assert "fixed 3 gate failure(s) by itself and the orchestrator saw none" in text


def test_a_repeated_guard_failure_is_listed_once_with_a_count(tmp_path):
    guard = {"ts": "2026-09-20T22:15:50+02:00", "event": "guard_result", "phase": 1,
             "ok": False, "problem": "Tests were skipped or marked xfail:\ntests/test_a.py: x"}
    text = render(collect(make_run(tmp_path, timeline=[*TIMELINE, guard, guard])))
    assert "- test guard (2x): Tests were skipped or marked xfail: tests/test_a.py: x" in text


def test_state_files_fill_in_for_a_phase_the_timeline_never_finished(tmp_path):
    run = make_run(tmp_path, timeline=TIMELINE[:2], states=[
        (1, {"phase": 1, "status": "BLOCKED", "reason": "the design is ambiguous",
             "unmet_criteria": ["the second criterion"], "fix_rounds_self": 2})])
    phase = collect(run).phases[0]
    assert phase.status == "agent said BLOCKED, no phase_end"
    assert phase.reason == "the design is ambiguous" and phase.self_rounds == 2
    assert "unmet criterion: the second criterion" in render(collect(run))


def test_a_run_without_a_timeline_still_summarises_what_it_has(tmp_path):
    summary = collect(make_run(tmp_path))
    assert "Incomplete" in render(summary) and "timeline.jsonl" in render(summary)
    assert summary.phases[0].usage.input == 0       # the events file is still readable


def test_summarize_writes_summary_md_into_the_run(tmp_path):
    run = make_run(tmp_path, timeline=TIMELINE)
    text = summarize(run)
    assert (run.root / "summary.md").read_text(encoding="utf-8") == text


def test_the_commit_sha_is_in_the_table(tmp_path):
    """The rollback point is the most useful thing in a morning report; it used to be
    collected off the timeline and then never rendered."""
    text = render(collect(make_run(tmp_path, timeline=TIMELINE)))
    assert "| Commit " in text and "aaaaaaa" in text


def test_cache_hits_are_summed_and_shown(tmp_path):
    summary = collect(make_run(tmp_path, fixture="pi_usage.jsonl"))
    assert summary.phases[0].usage.cache_read == 6144
    assert "Cached" in render(summary)
