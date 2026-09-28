"""`styre watch` reads runs off disk; these tests build run directories and read them back.

No server is started for the readers — they are plain functions over files. The HTTP layer
gets one smoke test through the handler, because a route that 500s is the one failure a
monitor must not have.
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from styre import watch
from styre.config import DEFAULT_TIMEOUT
from styre.rundir import RUNS


@pytest.fixture(autouse=True)
def in_repo(tmp_path, monkeypatch):
    """Run every test in a throwaway directory, and drop the tail cache between them."""
    monkeypatch.chdir(tmp_path)
    watch._TAILS.clear()
    # The live panel asks the model server for its status. Never from a test: that would
    # read the developer's pi config and call their model host. test_server.py covers it.
    monkeypatch.setattr(watch.server, "status", lambda: None)
    monkeypatch.setattr(watch.server, "provider", lambda: None)
    return tmp_path


def write_run(run_id, timeline, events=None, logs=None):
    """Create `.styre/runs/<id>/` with a timeline, event files and phase logs."""
    root = RUNS / run_id
    (root / "logs").mkdir(parents=True)
    (root / "timeline.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in timeline), encoding="utf-8")
    for n, lines in (events or {}).items():
        (root / "logs" / f"phase{n}.events.jsonl").write_text(
            "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    for n, text in (logs or {}).items():
        (root / "logs" / f"phase{n}.log").write_text(text, encoding="utf-8")
    return root


def stamp(offset_seconds=0):
    return (datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc)
            + timedelta(seconds=offset_seconds)).isoformat()


def message_end(ts, total, output=10):
    """One wrapped pi event, the shape `logs/phaseN.events.jsonl` actually holds."""
    return {"ts": ts, "line": json.dumps(
        {"type": "message_end",
         "message": {"usage": {"totalTokens": total, "output": output}}})}


def message_start(ts):
    return {"ts": ts, "line": json.dumps({"type": "message_start"})}


def tool_error(ts, name="edit"):
    return {"ts": ts, "line": json.dumps(
        {"type": "tool_execution_end", "toolName": name, "isError": True})}


FINISHED = [
    {"ts": stamp(0), "event": "run_start", "run": "r1", "design": "d.md", "branch": "b",
     "phases": 1, "from_phase": 1},
    {"ts": stamp(1), "event": "pi_start", "phase": 1, "step": "builder"},
    {"ts": stamp(60), "event": "pi_end", "phase": 1, "step": "builder", "seconds": 59, "rc": 0},
    {"ts": stamp(61), "event": "gate_end", "phase": 1, "step": "builder",
     "command": "pytest", "seconds": 1, "rc": 0},
    {"ts": stamp(62), "event": "guard_result", "phase": 1, "ok": True, "problem": None},
    {"ts": stamp(63), "event": "commit", "phase": 1, "sha": "a" * 40, "subject": "Phase 1"},
    {"ts": stamp(64), "event": "phase_end", "phase": 1, "title": "Phase 1: One",
     "status": "committed", "rounds": 0, "fix_rounds_self": 0, "unmet_criteria": []},
    {"ts": stamp(65), "event": "run_end", "exit_code": 0, "committed": 1},
]

RUNNING = FINISHED[:2]   # a run_start and a pi_start, nothing closed


def test_runs_are_listed_newest_first():
    write_run("20260101-000000", FINISHED)
    write_run("20260202-000000", FINISHED)
    assert [r.id for r in watch.runs()] == ["20260202-000000", "20260101-000000"]


def test_no_runs_directory_is_not_an_error():
    assert watch.runs() == []
    assert "No runs" in watch.index_html()


def test_index_reads_only_the_timeline(monkeypatch):
    """The run list must not open an events file: that is what keeps it instant."""
    write_run("20260101-000000", FINISHED, events={1: [message_end(stamp(30), 1000)]})

    def fail(*args, **kwargs):
        raise AssertionError("the index opened an events file")

    monkeypatch.setattr(watch, "tail_for", fail)
    body = watch.index_html()
    assert "20260101-000000" in body
    assert "exit 0" in body


def test_a_finished_run_is_not_live():
    write_run("20260101-000000", FINISHED)
    run = watch.find_run("20260101-000000")
    summary = watch.timeline_only(run)
    assert watch.unclosed(summary) is False
    assert watch.run_state(run, summary) == ("exit 0", "dim", False)
    assert watch.live_step(run) is None
    assert "exit 0" in watch.live_html(run)


def test_an_open_pi_start_is_the_live_step():
    write_run("20260101-000000", RUNNING)
    run = watch.find_run("20260101-000000")
    summary = watch.timeline_only(run)
    assert watch.unclosed(summary) is True
    assert watch.run_state(run, summary)[::2] == ("running", True)
    phase, step, _ = watch.live_step(run)
    assert (phase, step) == (1, "builder")


def backdate(root, seconds):
    """Age every file in a run directory, the way a run killed two days ago is aged."""
    when = time.time() - seconds
    for path in [root, *root.rglob("*")]:
        os.utime(path, (when, when))


def test_a_killed_run_is_abandoned_not_running():
    """A missing run_end is not a heartbeat: app's 20260921-045131 held 17 starts against
    5 ends, and every one of those dead invocations read as live until this existed."""
    root = write_run("20260101-000000", RUNNING, events={1: [message_end(stamp(0), 1000)]})
    backdate(root, DEFAULT_TIMEOUT + 60)
    run = watch.find_run("20260101-000000")
    label, css, live = watch.run_state(run, watch.timeline_only(run))
    assert live is False and css == "bad" and "abandoned" in label
    assert "abandoned" in watch.live_html(run)
    assert "abandoned" in watch.index_html()


def test_a_quiet_but_recent_run_is_still_running():
    """pi prints nothing between tool_execution_start and end, so a long tool call looks
    exactly like a stall. Say how quiet it is; do not call it dead."""
    root = write_run("20260101-000000", RUNNING, events={1: [message_end(stamp(0), 1000)]})
    backdate(root, watch.STALE_SECONDS + 60)
    run = watch.find_run("20260101-000000")
    label, css, live = watch.run_state(run, watch.timeline_only(run))
    assert live is True and css == "warn" and "silent" in label


def test_between_phases_reports_no_open_process():
    """A phase that ended without the next one starting is a real state, not an error."""
    write_run("20260101-000000", FINISHED[:3])
    run = watch.find_run("20260101-000000")
    assert watch.live_step(run) is None
    assert "Between phases" in watch.live_html(run)


def test_live_panel_shows_the_server_and_the_context_ceiling(monkeypatch):
    """The server's own status sits next to the phase, and peak context reads against the
    window pi was given. Stubbed: test_server.py covers finding and reading the server."""
    write_run("20260101-000000", RUNNING, events={1: [message_end(stamp(0), 59447)]})
    monkeypatch.setattr(watch.server, "provider", lambda: {"context_window": 120000})
    monkeypatch.setattr(watch.server, "status", lambda: {
        "server": "modelhost", "ready": True, "memory_pressure": "normal", "waiting": 1,
        "waiting_memory": 1, "suspended": 0, "oldest_wait_ms": 42000, "max_context": 262144})
    body = watch.live_html(watch.find_run("20260101-000000"))
    assert "59,447 <span class=dim>of 120,000</span>" in body
    assert "modelhost:" in body and "ready" in body and "memory normal" in body
    assert "1 waiting, 1 on memory (oldest 42s)" in body
    assert "server max ctx 262,144" in body


def test_an_unreachable_server_is_said_plainly():
    body = watch.server_html({"server": "modelhost", "error": "unreachable (timed out)"})
    assert "class=bad" in body and "unreachable" in body
    assert watch.server_html(None) == ""   # mlxserve: no /status, so no line at all


def test_series_and_peak_come_from_message_end():
    write_run("20260101-000000", RUNNING, events={1: [
        message_end(stamp(0), 1000), message_end(stamp(60), 5000),
        message_end(stamp(120), 3000)]})
    run = watch.find_run("20260101-000000")
    assert watch.series(run, 1) == [(0.0, 1000), (60.0, 5000), (120.0, 3000)]
    assert watch.tail_for(run, 1).peak == 5000          # a high-water mark, never the last


def test_the_tail_reads_only_what_was_appended():
    root = write_run("20260101-000000", RUNNING, events={1: [message_end(stamp(0), 1000)]})
    run = watch.find_run("20260101-000000")
    watch.tail_for(run, 1)
    path = root / "logs" / "phase1.events.jsonl"
    before = watch._TAILS[(run.id, 1)].offset
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(message_end(stamp(60), 7000)) + "\n")
    tail = watch.tail_for(run, 1)
    assert tail.offset > before
    assert [y for _, y in tail.points] == [1000, 7000]  # the first line was not re-read


def test_a_half_written_line_is_read_once_it_is_whole():
    """The file is appended to while pi runs, so the last line is regularly a fragment."""
    root = write_run("20260101-000000", RUNNING, events={1: [message_end(stamp(0), 1000)]})
    run = watch.find_run("20260101-000000")
    path = root / "logs" / "phase1.events.jsonl"
    whole = json.dumps(message_end(stamp(60), 7000))
    with open(path, "a", encoding="utf-8") as f:
        f.write(whole[:20])
    assert [y for _, y in watch.tail_for(run, 1).points] == [1000]
    with open(path, "a", encoding="utf-8") as f:
        f.write(whole[20:] + "\n")
    assert [y for _, y in watch.tail_for(run, 1).points] == [1000, 7000]


def test_a_replaced_events_file_is_read_again_from_the_start():
    root = write_run("20260101-000000", RUNNING, events={1: [
        message_end(stamp(0), 1000), message_end(stamp(60), 2000)]})
    run = watch.find_run("20260101-000000")
    watch.tail_for(run, 1)
    (root / "logs" / "phase1.events.jsonl").write_text(
        json.dumps(message_end(stamp(0), 42)) + "\n", encoding="utf-8")
    assert [y for _, y in watch.tail_for(run, 1).points] == [42]


def test_tokens_per_second_is_model_time_not_wall_time():
    """Two messages of 100 output tokens, each taking 10s, with a 1-hour gap between them:
    20 tok/s of model time. Output over the wall clock would say 0.05 and be useless — it
    read 0.60 on a real phase whose events file spanned a failed attempt and its resume."""
    write_run("20260101-000000", RUNNING, events={1: [
        message_start(stamp(0)), message_end(stamp(10), 5000, output=100),
        message_start(stamp(3600)), message_end(stamp(3610), 9000, output=100)]})
    run = watch.find_run("20260101-000000")
    assert watch.tail_for(run, 1).tokens_per_second == pytest.approx(10.0)


def test_tokens_per_second_is_none_without_a_timed_message():
    """A message_end with no message_start before it cannot be timed, and absent is not 0."""
    write_run("20260101-000000", RUNNING, events={1: [message_end(stamp(10), 5000)]})
    run = watch.find_run("20260101-000000")
    assert watch.tail_for(run, 1).tokens_per_second is None
    assert watch.fmt_rate(None) == "-"


def test_tool_errors_are_counted_by_name():
    write_run("20260101-000000", RUNNING, events={1: [
        tool_error(stamp(1)), tool_error(stamp(2)), tool_error(stamp(3), "bash")]})
    run = watch.find_run("20260101-000000")
    assert watch.tail_for(run, 1).tool_errors == {"edit": 2, "bash": 1}


def test_staleness_is_none_without_an_events_file():
    write_run("20260101-000000", RUNNING)
    run = watch.find_run("20260101-000000")
    assert watch.staleness(run, 1) is None


def test_the_danger_line_is_the_lowest_peak_that_stopped():
    stopped = FINISHED[:6] + [
        {"ts": stamp(64), "event": "phase_end", "phase": 1, "title": "Phase 1: One",
         "status": "stopped", "reason": "empty response", "rounds": 2, "unmet_criteria": []},
        {"ts": stamp(65), "event": "run_end", "exit_code": 1, "committed": 0,
         "stopped": "Stopped at phase 1"}]
    write_run("20260101-000000", stopped, events={1: [message_end(stamp(0), 90000)]})
    write_run("20260202-000000", FINISHED, events={1: [message_end(stamp(0), 120000)]})
    summaries = [watch.collect(r) for r in watch.runs()]
    assert watch.danger_line(summaries) == 90000        # the committed 120k is not a limit


def test_no_stopped_phase_means_no_danger_line():
    write_run("20260101-000000", FINISHED, events={1: [message_end(stamp(0), 120000)]})
    assert watch.danger_line([watch.collect(r) for r in watch.runs()]) is None
    assert "no danger line" in watch.run_html(watch.find_run("20260101-000000"))


def test_sparkline_is_inline_svg_with_no_external_request():
    svg = watch.sparkline([(0, 1000), (60, 2000)], threshold=1500)
    assert svg.startswith("<svg") and "polyline" in svg and "line" in svg
    assert "http" not in svg
    assert "no context measured" in watch.sparkline([])
    assert "circle" in watch.sparkline([(0, 1000)])     # one sample is a dot, not a slope


def test_log_tail_returns_whole_lines_from_the_end():
    write_run("20260101-000000", RUNNING, logs={1: "".join(f"line {i}\n" for i in range(500))})
    run = watch.find_run("20260101-000000")
    tail = watch.log_tail(run, 1, limit=40)
    assert tail.endswith("line 499\n")
    assert not tail.startswith("ine")                   # never half a line


def test_a_run_page_carries_the_phase_table_and_where_to_look():
    write_run("20260101-000000", FINISHED, events={1: [message_end(stamp(0), 1234)]})
    body = watch.run_html(watch.find_run("20260101-000000"))
    assert "Phase 1: One" in body and "1,234" in body and "Where to look" in body
    assert "aaaaaaa" in body                            # the commit sha, short


def test_find_run_refuses_anything_but_a_directory_name():
    write_run("20260101-000000", FINISHED)
    assert watch.find_run("20260101-000000") is not None
    for bad in ("../../etc", "a/b", "", None, ".", ".."):
        assert watch.find_run(bad) is None


def test_the_handler_serves_the_index_a_run_and_the_live_json():
    """One smoke test through the real routes: a monitor that 500s is worse than none."""
    write_run("20260101-000000", RUNNING, events={1: [message_end(stamp(0), 1000)]},
              logs={1: "working\n"})
    seen = []

    class Fake(watch.Handler):
        def __init__(self, path):
            self.path = path
            self.wfile = self
            self.headers_sent = {}

        def send_response(self, code):
            seen.append(code)

        def send_header(self, k, v):
            self.headers_sent[k] = v

        def end_headers(self):
            pass

        def write(self, blob):
            self.body = blob.decode("utf-8")

    for path, expect in (("/", "20260101-000000"), ("/run/20260101-000000", "Phases"),
                         ("/api/live/20260101-000000", "peak ctx"), ("/nope", "Not found"),
                         ("/run/../secret", "Not found")):
        h = Fake(path)
        h.do_GET()
        assert expect in h.body, (path, h.body[:200])
    assert seen == [200, 200, 200, 404, 404]   # a missing run is a 404, not a 200 page


def test_terminal_shows_the_same_live_facts_as_the_page(monkeypatch):
    """`styre watch -t` renders live_facts too, so the two views cannot disagree."""
    write_run("20260101-000000", RUNNING,
              events={1: [message_start(stamp(0)), message_end(stamp(10), 59447, output=100)]},
              logs={1: "[+00:01] ⚙ read src/a.py ✓\n"})
    monkeypatch.setattr(watch.server, "provider", lambda: {"context_window": 120000})
    monkeypatch.setattr(watch.server, "status", lambda: {
        "server": "modelhost", "ready": True, "memory_pressure": "normal", "waiting": 0,
        "waiting_memory": 0, "suspended": 0, "oldest_wait_ms": 0, "max_context": 262144})
    text = "\n".join(watch.live_text(watch.find_run("20260101-000000")))
    assert "phase 1 builder" in text
    assert "peak ctx 59,447 of 120,000" in text
    assert "tok/s 10.0" in text
    assert "modelhost: ready · memory normal · nothing queued" in text
    assert "read src/a.py" in text
    assert "\033[" not in text          # no colour unless asked


def test_terminal_once_prints_and_exits(capsys):
    write_run("20260101-000000", FINISHED)
    assert watch.terminal(once=True) == 0
    out = capsys.readouterr().out
    assert "20260101-000000" in out and "exit 0" in out and "Nothing is running" in out


def test_terminal_without_runs_says_where_to_run_it(capsys):
    watch.terminal(once=True)
    assert "inside the target repository" in capsys.readouterr().out
