"""The event renderer, against real captured pi output rather than assumptions."""
import json
import time
from pathlib import Path

import pytest

from styre.process import elapsed, render_event

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def transcript(name):
    state, out = {}, []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(render_event(json.loads(line), state))
    return "".join(out)


def test_simple_reply_renders_its_text():
    assert "OK" in transcript("pi_simple.jsonl")


def test_tool_call_is_shown_with_its_first_argument():
    text = transcript("pi_toolcall.jsonl")
    assert "⚙ bash" in text
    assert "✓" in text or "[error]" in text


def test_thinking_is_dropped():
    raw = (FIXTURES / "pi_toolcall.jsonl").read_text(encoding="utf-8")
    assert "thinking_delta" in raw  # the fixture really does contain thinking
    assert "thinking" not in transcript("pi_toolcall.jsonl")


@pytest.mark.parametrize("name", ["pi_simple.jsonl", "pi_toolcall.jsonl", "pi_session.jsonl"])
def test_rendering_is_much_smaller_than_the_raw_stream(name):
    raw = len((FIXTURES / name).read_text(encoding="utf-8"))
    assert len(transcript(name)) < raw


def test_unknown_events_render_nothing():
    assert render_event({"type": "agent_settled"}, {}) == ""
    assert render_event({}, {}) == ""


def test_tool_error_is_marked():
    assert render_event({"type": "tool_execution_end", "isError": True}, {}) == " [error]"


def test_elapsed_is_minutes_into_the_step_and_absent_without_a_clock():
    assert elapsed({}) == ""                                  # nothing started the clock
    assert elapsed({"t0": time.monotonic()}) == "[+00:00] "
    assert elapsed({"t0": time.monotonic() - 125}) == "[+02:05] "


def test_a_tool_call_is_stamped_with_how_far_into_the_step_it_is():
    state = {"t0": time.monotonic() - 74}
    event = {"type": "message_update",
             "assistantMessageEvent": {"type": "toolcall_start", "toolName": "bash"}}
    assert render_event(event, state) == "\n[+01:14] ⚙ bash "
