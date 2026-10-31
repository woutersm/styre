"""The summarize readers, against the captured pi output in tests/fixtures/."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from styre.rundir import RunDir
from styre.summarize import Phase, Usage, collect, read_events, read_stamped_events, render, summarize

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def events_file(path, source, seconds=1):
    """Wrap a captured pi stream the way stream_pi() writes it: one arrival stamp per line."""
    ts = datetime(2026, 9, 20, 22, 0, 0).astimezone()
    with open(path, "w", encoding="utf-8") as f:
        for i, line in enumerate(source.read_text(encoding="utf-8").splitlines()):
            f.write(json.dumps({"ts": (ts + timedelta(seconds=i * seconds)).isoformat(),
                                "line": line}) + "\n")


def make_run(path, timeline=(), states=(), fixture="pi_toolcall.jsonl", phases=(1,),
             run_id="20260920-220000"):
    run = RunDir(path / run_id)
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


def test_real_token_counts_are_read_off_a_capture(tmp_path):
    # pi_toolcall.jsonl is two assistant messages: the peak is the larger totalTokens, output,
    # reasoning and cache hits are summed. A reported `reasoning` is believed when it is backed.
    usage = collect(make_run(tmp_path)).phases[0].usage
    assert (usage.peak, usage.output, usage.reasoning, usage.cache_read) == (1907, 63, 31, 3584)


def test_request_tokens_and_cache_hit_are_read_off_the_capture(tmp_path):
    # pi_toolcall.jsonl through make_run stamps one second per line: the two assistant
    # requests are 29 and 97 uncached input tokens (126 total) against 3584 cache hits.
    usage = collect(make_run(tmp_path)).phases[0].usage
    assert usage.requests == 2
    assert (usage.input, usage.cache_read) == (126, 3584)
    assert usage.cache_hit == 3584 / (126 + 3584)


def test_prefill_and_decode_are_measured_off_the_arrival_stamps(tmp_path):
    # With one second per line, request 1 is start line 8, first update line 9, end line 36:
    # prefill 1 s, decode 27 s; request 2 is 1 s and 19 s.
    usage = collect(make_run(tmp_path)).phases[0].usage
    assert usage.prefill_seconds == 2.0
    assert usage.decode_seconds == 46.0
    assert usage.timed == 2


def test_a_request_whose_stamps_are_missing_counts_but_adds_no_time(tmp_path):
    run = make_run(tmp_path)
    # Strip the arrival stamps: the requests still count, but nothing can be timed.
    stamped = run.events(1).read_text(encoding="utf-8").splitlines()
    lines = [json.dumps({k: v for k, v in json.loads(raw).items() if k != "ts"}) for raw in stamped]
    run.events(1).write_text("".join(raw + "\n" for raw in lines), encoding="utf-8")
    usage = collect(run).phases[0].usage
    assert usage.requests == 2       # still counted
    assert usage.timed == 0         # none timed
    assert (usage.prefill_seconds, usage.decode_seconds) == (0.0, 0.0)


def test_stamped_events_yield_the_timestamp_and_drop_it_in_read_events(tmp_path):
    path = tmp_path / "e.jsonl"
    path.write_text('{"ts": "2026-09-20T22:00:00+02:00", "line": "{\\"type\\": \\"agent_end\\"}"}\n' +
                    '{"line": "{\\"type\\": \\"turn_end\\"}"}\n', encoding="utf-8")
    stamped = list(read_stamped_events(path))
    assert stamped[0][0] == datetime(2026, 9, 20, 22, 0, 0).astimezone()
    assert stamped[1][0] is None                          # missing ts stays None
    assert [e["type"] for e in read_events(path)] == ["agent_end", "turn_end"]


def test_cache_hit_is_none_when_there_were_no_prompt_tokens():
    u = Usage()
    u.add({"input": 0, "output": 40, "cacheRead": 0})
    assert u.cache_hit is None


def test_the_summary_has_a_model_time_table_and_the_phases_table_drops_cached(tmp_path):
    run = make_run(tmp_path, timeline=TIMELINE)
    text = render(collect(run))
    model_time = text.split("## Model time")[1].split("## ")[0]
    assert "## Model time" in text
    assert "96.6%" in model_time
    phases = text.split("## Phases")[1].split("## ")[0]
    assert "Cached" not in phases


def test_model_time_shows_prefill_and_decode_rates(tmp_path):
    # 126 uncached input tokens over 2 s of prefill, 63 output tokens over 46 s of decode.
    text = render(collect(make_run(tmp_path, timeline=TIMELINE)))
    model_time = text.split("## Model time")[1].split("## ")[0]
    assert "Prefill tok/s" in model_time and "Decode tok/s" in model_time
    assert "| 63.0 " in model_time and "| 1.4 " in model_time


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
     "design": "d.md", "branch": "styre/d", "pi_version": "0.85.1", "styre": "0.1.0",
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


def model_call(role="planner", ok=True, tokens_in=100, cached_in=80, tokens_out=10,
               thinking=3, cost=0.01, seconds=1.0, error=None):
    return {"ts": "t", "event": "model_call", "role": role, "model": "claude-opus-5-5",
            "tokens_in": tokens_in, "cached_in": cached_in, "cache_write": 0, "tokens_out": tokens_out,
            "thinking": thinking, "cost_usd": cost, "turns": 1, "seconds": seconds,
            "ok": ok, "error": error}


MODEL_CALL_TIMELINE = [
    {"ts": "2026-09-20T22:00:00+02:00", "event": "run_start", "run": "20260920-220000",
     "design": "d.md", "branch": "styre/d", "pi_version": "0.85.1", "styre": "0.1.0",
     "design_sha256": "abc123", "templates": "def456", "phases": 2, "from_phase": 1},
    model_call(tokens_in=100, cached_in=80, tokens_out=10, thinking=3, cost=0.01, seconds=1.0),
    model_call(ok=False, tokens_in=200, cached_in=0, tokens_out=5, thinking=0, cost=0.02,
               seconds=2.0, error="The planner call reported an error: x"),
    {"ts": "2026-09-20T22:16:00+02:00", "event": "run_end", "exit_code": 0, "committed": 1,
     "stopped": None},
]


def test_model_calls_are_shown_after_model_time(tmp_path):
    # Two planner calls, one failed: one row per role with the summed tokens, plus a total.
    text = render(collect(make_run(tmp_path, timeline=MODEL_CALL_TIMELINE)))
    section = text.split("## Model calls")[1].split("## ")[0]
    assert section.index("| planner ") < section.index("| total ")
    assert "2" in section and "1" in section and "300" in section
    assert "80" in section and "15" in section and "0.03" in section
    assert "0.1" in section  # 1 + 2 seconds, to the minute
    assert section.index("| planner ") < len(section)
    # the section sits after `## Model time`
    assert text.index("## Model time") < text.index("## Model calls") < text.index("## Where to look")


def test_a_run_without_model_calls_has_no_section(tmp_path):
    text = render(collect(make_run(tmp_path, timeline=TIMELINE)))
    assert "## Model calls" not in text


def test_a_plan_only_run_summarizes_without_an_error(tmp_path):
    # run_start kind: "plan" and no phases: header, no phase tables, its Model calls.
    timeline = [
        {"ts": "2026-09-20T22:00:00+02:00", "event": "run_start", "run": "20260920-220000",
         "design": "d.md", "kind": "plan", "styre": "0.1.0"},
        model_call(tokens_in=1234, cached_in=1000, tokens_out=567, cost=0.16, seconds=6.1),
        {"ts": "2026-09-20T22:01:00+02:00", "event": "run_end", "exit_code": 0,
         "stopped": None},
    ]
    text = render(collect(make_run(tmp_path, timeline=timeline, phases=())))
    assert "# Run 20260920-220000" in text and "design d.md" in text
    assert "## Model calls" in text and "1,234" in text and "0.16" in text
    assert "## Phases" not in text and "## Model time" not in text


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
    assert "0.85.1" in text and "styre/d" in text and "templates def456" in text


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


def test_acceptance_edits_are_listed_once_with_a_count(tmp_path):
    def restored(step):
        return {"ts": "2026-09-20T22:15:50+02:00", "event": "acceptance_restored",
                "phase": 1, "step": step, "paths": ["tests/test_accept_phase1.py"]}
    timeline = [*TIMELINE, restored("builder"), restored("fix 1")]
    run = make_run(tmp_path, timeline=timeline)
    phase = collect(run).phases[0]
    assert phase.acceptance_edits == ["tests/test_accept_phase1.py"] * 2
    text = render(collect(run))
    assert "- acceptance test edited by the builder and restored (2x): " \
           "tests/test_accept_phase1.py" in text


def test_a_single_acceptance_edit_has_no_count(tmp_path):
    timeline = [*TIMELINE, {"ts": "t", "event": "acceptance_restored", "phase": 1,
                            "step": "builder", "paths": ["tests/test_accept_phase1.py"]}]
    text = render(collect(make_run(tmp_path, timeline=timeline)))
    assert "- acceptance test edited by the builder and restored: " \
           "tests/test_accept_phase1.py" in text
    assert "restored (" not in text


def test_acceptance_edits_group_by_path_across_phases(tmp_path):
    timeline = [*TIMELINE,
                {"ts": "t", "event": "acceptance_restored", "phase": 1, "step": "builder",
                 "paths": ["tests/test_accept_a.py"]},
                {"ts": "t", "event": "acceptance_restored", "phase": 2, "step": "fix 1",
                 "paths": ["tests/test_accept_b.py", "tests/test_accept_a.py"]}]
    run = make_run(tmp_path, timeline=timeline, phases=(1, 2))
    phases = collect(run).phases
    assert phases[0].acceptance_edits == ["tests/test_accept_a.py"]
    assert phases[1].acceptance_edits == ["tests/test_accept_b.py", "tests/test_accept_a.py"]
    text = render(collect(run))
    assert "- acceptance test edited by the builder and restored: tests/test_accept_a.py" in text
    assert "- acceptance test edited by the builder and restored: tests/test_accept_b.py" in text


def test_a_run_without_acceptance_edits_is_unchanged(tmp_path):
    text = render(collect(make_run(tmp_path, timeline=TIMELINE)))
    assert "acceptance" not in text


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
    assert summary.phases[0].usage.peak == 1907    # the events file is still readable


def test_summarize_writes_summary_md_into_the_run(tmp_path):
    run = make_run(tmp_path, timeline=TIMELINE)
    text = summarize(run)
    assert (run.root / "summary.md").read_text(encoding="utf-8") == text


def test_the_commit_sha_is_in_the_table(tmp_path):
    """The rollback point is the most useful thing in a run's report; it used to be
    collected off the timeline and then never rendered."""
    text = render(collect(make_run(tmp_path, timeline=TIMELINE)))
    assert "| Commit " in text and "aaaaaaa" in text


def test_cache_hits_are_summed_and_shown(tmp_path):
    summary = collect(make_run(tmp_path))
    assert summary.phases[0].usage.cache_read == 3584
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


def test_a_resumed_run_reports_the_versions_it_last_ran_on(tmp_path):
    """Run.first is where the run began; the versions are the ones the latest invocation used."""
    start = next(e for e in TIMELINE if e["event"] == "run_start")
    resumed = {**start, "ts": "2026-09-21T08:00:00+02:00", "pi_version": "0.87.1", "styre": "0.9.0"}
    text = render(collect(make_run(tmp_path, timeline=[*TIMELINE, resumed])))
    header = text.split("\n## ", 1)[0]
    assert "pi 0.87.1" in header and "styre 0.9.0" in header
    assert "0.85.1" not in header and "started 2026-09-20 22:00" in header


def with_agent_gates(run, n, results):
    """Append styre_gate calls to a phase's events, as styre-tools.js reports them."""
    path = run.events(n)
    with open(path, "a", encoding="utf-8") as f:
        for i, passed in enumerate(results):
            line = {"type": "tool_execution_end", "toolCallId": f"g{i}", "toolName": "styre_gate",
                    "isError": False,
                    "result": {"content": [{"type": "text", "text": json.dumps({"passed": passed})}]}}
            f.write(json.dumps({"ts": "2026-09-20T22:20:00+02:00", "line": json.dumps(line)}) + "\n")


def quiet_timeline(self_rounds):
    timeline = [e for e in TIMELINE if e["event"] not in ("gate_end", "pi_end")]
    return [{**e, "rounds": 0, "fix_rounds_self": self_rounds} if e["event"] == "phase_end" else e
            for e in timeline]


def test_a_red_styre_gate_on_the_way_to_green_is_not_called_out(tmp_path):
    """With styre_gate, running the gate early and seeing it red is the workflow, not a sign
    of an unclear criterion (a real run, 2026-09-30: 6 of 8 phases flagged for it)."""
    run = make_run(tmp_path, timeline=quiet_timeline(1))
    with_agent_gates(run, 1, [False, True])
    text = render(collect(run))
    assert "by itself" not in text and "red" not in text


def test_a_styre_gate_that_stayed_red_is_called_out(tmp_path):
    run = make_run(tmp_path, timeline=quiet_timeline(3))
    with_agent_gates(run, 1, [False, False, False, True])
    text = render(collect(run))
    assert "the agent's own gate was red 3 times before it passed" in text


def test_a_stopped_phase_names_its_last_progress_file(tmp_path):
    """A resume starts the phase without it, so the director copies it into the design first."""
    run = make_run(tmp_path, phases=(1, 2), timeline=[
        {"event": "phase_end", "phase": 1, "status": "committed"},
        {"event": "phase_end", "phase": 2, "status": "stopped", "reason": "gate failed"}])
    for n in (1, 2):
        run.progress(n).write_text("Done: x\nNow: y\nNext: z\nLearned: w\n", encoding="utf-8")
    text = render(collect(run))
    # The run's real directory, not `.styre/runs/<id>`: summarize also takes a path.
    assert f"`{run.progress(2).as_posix()}`" in text
    assert "phase1.progress.md" not in text


# --- compare -----------------------------------------------------------------


def fast_timeline():
    """TIMELINE where phase 1 took 300 agent seconds in total: 5.0 minutes, against the 900
    (15.0) of the plain TIMELINE."""
    return [dict(e, seconds=300.0 if e["step"] == "builder" else 0.0)
            if e["event"] == "pi_end" else dict(e) for e in TIMELINE]


def test_compare_puts_two_runs_side_by_side(tmp_path):
    """`15.0` is TIMELINE's 900 s of agent time and `5.0` is 300 s: the exit criterion's
    row, exactly."""
    from styre.summarize import compare
    a = collect(make_run(tmp_path / "a", timeline=TIMELINE))
    b = collect(make_run(tmp_path / "b", timeline=fast_timeline()))
    text = compare(a, b)
    assert text.startswith("# Compare 20260920-220000 → 20260920-220000")
    assert "- 20260920-220000: design d.md, styre 0.1.0" in text
    assert "| 1 | Phase 1: One | committed → committed | 15.0 → 5.0 |" in text
    # A total row, the same way: summed agent minutes.
    assert "|  | total | - → - | 15.0 → 5.0 |" in text


def test_a_phase_present_in_only_one_run_shows_a_dash(tmp_path):
    from styre.summarize import compare
    a = collect(make_run(tmp_path / "a", timeline=TIMELINE, phases=(1, 2)))
    b = collect(make_run(tmp_path / "b", timeline=fast_timeline(), phases=(1,)))
    text = compare(a, b)
    # Phase 2 ran in A (no phase_end in the timeline, so its status is unknown) and not in B.
    assert "| 2 | Phase 2 | ? → - | - → - |" in text
    assert "| 1 | Phase 1: One | committed → committed | 15.0 → 5.0 |" in text


def test_compare_summarizes_both_runs_without_writing(tmp_path, monkeypatch, capsys):
    """The CLI prints and writes no file: neither run gets a summary.md."""
    import styre.rundir as rd
    from styre.cli import main
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rd, "RUNS", tmp_path / "runs")
    (tmp_path / "runs").mkdir()
    make_run(tmp_path / "runs", timeline=TIMELINE, run_id="a")
    make_run(tmp_path / "runs", timeline=fast_timeline(), run_id="b")
    assert main(["summarize", "--compare", "a", "b"]) == 0
    assert "| 1 | Phase 1: One | committed → committed | 15.0 → 5.0 |" in capsys.readouterr().out
    assert not (tmp_path / "runs" / "a" / "summary.md").exists()
    assert not (tmp_path / "runs" / "b" / "summary.md").exists()
