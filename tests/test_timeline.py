"""The timeline writer itself. The events a real run produces are covered end to end."""
import json

from styre.timeline import Timeline


def read(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


def test_events_are_appended_with_a_timestamp(tmp_path):
    tl = Timeline(tmp_path / "timeline.jsonl")
    tl.event("run_start", branch="overnight/x")
    tl.event("run_end", exit_code=0)
    events = read(tmp_path / "timeline.jsonl")
    assert [e["event"] for e in events] == ["run_start", "run_end"]
    assert events[0]["branch"] == "overnight/x" and events[1]["exit_code"] == 0
    assert all(e["ts"] for e in events)


def test_a_span_brackets_the_block_and_carries_its_result(tmp_path):
    tl = Timeline(tmp_path / "timeline.jsonl")
    with tl.span("gate", command="pytest -q") as end:
        end["rc"] = 1
    start, stop = read(tmp_path / "timeline.jsonl")
    assert (start["event"], stop["event"]) == ("gate_start", "gate_end")
    assert stop["command"] == "pytest -q" and stop["rc"] == 1
    assert stop["seconds"] >= 0


def test_a_span_is_closed_even_when_the_block_raises(tmp_path):
    tl = Timeline(tmp_path / "timeline.jsonl")
    try:
        with tl.span("pi", phase=1):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert [e["event"] for e in read(tmp_path / "timeline.jsonl")] == ["pi_start", "pi_end"]


def test_a_timeline_without_a_path_discards_everything():
    tl = Timeline()
    tl.event("run_start")
    with tl.span("gate", command="true") as end:
        end["rc"] = 0   # no file, no error: callers need not know whether a run dir exists
