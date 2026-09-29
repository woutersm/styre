"""The summarize readers, against the captured pi output in tests/fixtures/."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from styre.rundir import RunDir
from styre.summarize import Phase, Usage, collect, read_events, render, summarize

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
    assert phase.usage.peak == 0 and phase.usage.output == 0


def test_real_token_counts_are_read_off_a_post_fix_capture(tmp_path):
    # pi_usage.jsonl was captured after the mlxserve provider was set to report usage while
    # streaming, so unlike the older fixtures it carries real numbers.
    usage = collect(make_run(tmp_path, fixture="pi_usage.jsonl")).phases[0].usage
    assert (usage.peak, usage.output, usage.cache_read) == (7727, 23, 6144)
    # mlxserve reported `reasoning: 0` on a message that carries a thinking block. That zero is
    # not believed: the output is split by characters across the message's blocks instead.
    assert usage.reasoning == 22


def test_thinking_is_the_providers_count_unless_it_denies_visible_thinking():
    from styre.summarize import thinking_tokens
    thought = [{"type": "thinking", "thinking": "x" * 300}, {"type": "text", "text": "y" * 100}]
    assert thinking_tokens({"output": 40, "reasoning": 25}, thought) == 25   # believed
    assert thinking_tokens({"output": 40, "reasoning": 0}, thought) == 30    # 3/4 of 40
    assert thinking_tokens({"output": 40}, thought) == 30                    # none reported
    assert thinking_tokens({"output": 40, "reasoning": 0}, [{"type": "text", "text": "y"}]) == 0
    assert thinking_tokens({"output": 40}) is None                          # nothing says


def test_usage_takes_the_peak_context_and_sums_the_output():
    """`input` is per-step uncached prefill on this provider, not a running total, so the
    last value is one step's tail. `totalTokens` is the measured context."""
    u = Usage()
    u.add({"input": None, "output": None})                       # the first message_end
    u.add({"input": 1507, "output": 34, "cacheRead": 6144, "totalTokens": 7685})
    u.add({"input": 2200, "output": 50, "cacheRead": 1000, "totalTokens": 9935})
    u.add({"input": 1149, "output": 20, "cacheRead": 500, "totalTokens": 9000})
    assert (u.peak, u.output, u.cache_read) == (9935, 104, 7644)   # peak, not the last


def test_peak_context_is_absent_not_zero_when_the_provider_omits_it():
    u = Usage()
    u.add({"input": 10, "output": 40})
    assert u.peak is None                                 # absent, which is not zero


def test_the_run_total_peak_is_the_largest_phase_not_their_sum(tmp_path):
    run = make_run(tmp_path, timeline=TIMELINE)
    summary = collect(run)
    summary.phases[0].usage.peak = 44766
    summary.phases.append(Phase(n=2, usage=Usage(peak=86334)))
    text = render(summary)
    assert "86,334" in text and "131,100" not in text     # max, never a sum
    assert "Peak ctx" in text and "Input" not in text


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
    assert summary.phases[0].usage.peak == 0       # the events file is still readable


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


def test_relays_resumed_rounds_and_compactions_are_reported_not_failures(tmp_path):
    """A relay ends its step with RELAY_RC on purpose: counted as a fresh start, never as pi
    failing. pi's own compactions come from the events: a cancelled one (styre's extension) is
    counted quietly, a failed one is worth reading about."""
    timeline = [
        TIMELINE[0],
        {"ts": "t", "event": "pi_end", "phase": 1, "step": "builder", "seconds": 60.0, "rc": 75,
         "context": 81234},
        {"ts": "t", "event": "relay", "phase": 1, "step": "builder", "context": 81234,
         "relay_at": 72000, "relays": 1},
        {"ts": "t", "event": "pi_end", "phase": 1, "step": "builder relay 1", "seconds": 60.0, "rc": 0},
        {"ts": "t", "event": "pi_end", "phase": 1, "step": "fix 1", "seconds": 30.0, "rc": 0,
         "resumed": True},
        {"ts": "t", "event": "phase_end", "phase": 1, "title": "Phase 1: One", "status": "committed",
         "rounds": 1, "relays": 1, "fix_rounds_self": 0, "unmet_criteria": []},
    ]
    run = make_run(tmp_path, timeline)
    compactions = [
        {"type": "compaction_end", "reason": "threshold", "aborted": True},
        {"type": "compaction_end", "reason": "threshold", "aborted": False,
         "errorMessage": "Auto-compaction failed: generation hit the token cap"},
        {"type": "compaction_end", "reason": "threshold", "aborted": False,
         "errorMessage": "Auto-compaction failed: generation hit the token cap"},
    ]
    with open(run.events(1), "a", encoding="utf-8") as f:
        for e in compactions:
            f.write(json.dumps({"ts": "2026-09-20T22:05:00+02:00", "line": json.dumps(e)}) + "\n")
    [phase] = collect(run).phases
    assert phase.pi_failures == []
    assert phase.relays == [("builder", 81234)] and phase.resumed == 1
    assert phase.compactions_cancelled == 1 and len(phase.compactions_failed) == 2
    text = render(collect(run))
    assert "1 fresh start(s) because the context outgrew its budget (at 81,234 tokens)" in text
    assert "pi's compaction failed (2x): Auto-compaction failed: generation hit the token cap" in text
    assert "1 fix round(s) resumed their session" in text
    assert "pi exited" not in text


def test_history_lines_measure_this_repo_against_the_budget():
    from styre.summarize import history_lines
    small, large = Phase(n=1, title="Phase 1: Small"), Phase(n=2, title="Phase 2: Large")
    small.usage.add({"totalTokens": 40000})
    large.usage.add({"totalTokens": 110000})
    lines = history_lines([("run-a", small), ("run-a", large)], 72000)
    assert lines[0] == ("2 phase(s) in 1 run(s): median peak context 40,000, largest 110,000 "
                        "(Phase 2: Large, run-a).")
    assert "1 of these phases went past that:" in lines[1]
    assert lines[2].split() == ["110,000", "Phase", "2:", "Large", "(run-a)"]
    assert history_lines([], 72000) == []
