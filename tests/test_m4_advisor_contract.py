"""Acceptance: the advisor's call and its checks (styre/advisor.py, prompts.advisor_prompt).

No test calls a real model: tests/fake_claude.py stands in for `claude`.
"""
import json
from pathlib import Path

from styre.advisor import (
    ACTIONS,
    MAX_PATCHES,
    READ_TOOLS,
    Advice,
    Stall,
    advise,
    check,
    schema,
    split_problems,
)
from styre.design import parse_phases
from styre.prompts import advisor_prompt
from styre.timeline import Timeline

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FENCE = "`" * 3
ACCEPT = ("tests/test_thing_contract.py", "def test_thing_contract():\n    assert True\n")


def section(title, criterion="the thing works", gate="pytest -q", accept=None):
    """One phase section in the design format, built line by line."""
    lines = ["## " + title, "Build it.", ""]
    if accept is not None:
        lines += ["### Acceptance tests", "", f"`{accept[0]}`", FENCE + "python", accept[1] + FENCE, ""]
    lines += ["### Exit criteria", f"- {criterion}", "", "### Gate", FENCE, gate, FENCE, ""]
    return "\n".join(lines) + "\n"


PHASE = parse_phases(section("Phase 3: Build the thing", accept=ACCEPT))[0]
FIRST = section("Phase 3.1: The first half", criterion="the first half works", gate="pytest -q tests/a")
LAST = section("Phase 3.2: The second half", accept=ACCEPT)


def stall(**changes):
    fields = {"n": "3", "phase": PHASE, "context": "<the design excerpt for phase 3>",
              "reason": "gate failed: pytest -q, still failing after 2 fix rounds",
              "progress": "", "gate_report": "", "diff_stat": "",
              "log": ".styre/runs/r/logs/phase3.log"}
    fields.update(changes)
    return Stall(**fields)


def test_the_constants():
    assert ACTIONS == ("amend", "split", "patch", "stop")
    assert MAX_PATCHES == 2
    assert READ_TOOLS == ["Read", "Grep", "Glob"]


def test_schema_offers_exactly_the_actions_given_in_order():
    assert schema(["amend", "stop"]) == {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["amend", "stop"]},
                       "reason": {"type": "string"}, "text": {"type": "string"}},
        "required": ["action", "reason", "text"],
        "additionalProperties": False}
    assert schema(("stop", "patch"))["properties"]["action"]["enum"] == ["stop", "patch"]


# --- check -------------------------------------------------------------------------------


def test_check_accepts_a_good_amend():
    advice, problems = check({"action": "amend", "reason": "It lacked the format.", "text": "Use JSON."},
                             stall(), ["amend", "stop"])
    assert problems == []
    assert isinstance(advice, Advice)
    assert (advice.action, advice.reason, advice.text, advice.phases) == (
        "amend", "It lacked the format.", "Use JSON.", [])


def test_check_accepts_a_stop_with_no_text():
    advice, problems = check({"action": "stop", "reason": "The design is wrong.", "text": ""},
                             stall(), ["amend", "stop"])
    assert problems == [] and advice.action == "stop"


def test_check_refuses_an_answer_that_is_not_a_dict():
    advice, problems = check("stop", stall(), ["amend", "stop"])
    assert advice is None
    assert "The advice's action must be one of: amend, stop." in problems


def test_check_refuses_an_action_that_was_not_offered():
    advice, problems = check({"action": "patch", "reason": "r", "text": "t"}, stall(), ["amend", "stop"])
    assert advice is None
    assert problems == ["The advice's action must be one of: amend, stop."]


def test_check_refuses_a_blank_or_missing_reason():
    advice, problems = check({"action": "stop", "reason": "  ", "text": ""}, stall(), ["amend", "stop"])
    assert advice is None and problems == ["The advice has no reason."]
    advice, problems = check({"action": "stop", "text": ""}, stall(), ["amend", "stop"])
    assert advice is None and "The advice has no reason." in problems


def test_check_refuses_an_empty_text_for_amend_split_and_patch():
    for action in ("amend", "split", "patch"):
        advice, problems = check({"action": action, "reason": "r", "text": " "}, stall(), list(ACTIONS))
        assert advice is None, action
        assert "The advice's text is empty; amend, split and patch need it." in problems, action


def test_check_parses_a_good_split():
    advice, problems = check({"action": "split", "reason": "Too big.", "text": FIRST + LAST},
                             stall(), list(ACTIONS))
    assert problems == []
    assert [p.title for p in advice.phases] == ["Phase 3.1: The first half", "Phase 3.2: The second half"]


def test_check_returns_the_split_problems():
    bad = FIRST + section("Phase 3.2: The second half", gate="pytest -q tests/b", accept=ACCEPT)
    advice, problems = check({"action": "split", "reason": "Too big.", "text": bad}, stall(), list(ACTIONS))
    assert advice is None
    assert problems == ["The split's last phase must keep the phase's gate unchanged."]


# --- split_problems ----------------------------------------------------------------------


def test_a_good_split_has_no_problems():
    assert split_problems(PHASE, "3", FIRST + LAST) == []


def test_a_split_needs_2_or_3_phases():
    one = LAST.replace("Phase 3.2:", "Phase 3.1:")
    assert "The split has 1 phase; it must have 2 or 3." in split_problems(PHASE, "3", one)


def test_each_part_title_carries_the_phase_number():
    text = FIRST + LAST.replace("Phase 3.2:", "Phase 3.3:")
    assert split_problems(PHASE, "3", text) == ["Split phase 2's title must start with 'Phase 3.2:'."]


def test_the_split_is_validated_like_a_design():
    no_gate = "\n".join(["## Phase 3.1: No gate", "Build it.", "", "### Exit criteria", "- it works", ""])
    assert "Phase 1 has no '### Gate' code block." in split_problems(PHASE, "3", no_gate + "\n" + LAST)


def test_the_last_part_keeps_the_gate_the_criteria_and_the_acceptance_tests():
    cases = {
        "gate": section("Phase 3.2: The second half", gate="pytest -q tests/b", accept=ACCEPT),
        "exit criteria": section("Phase 3.2: The second half", criterion="something else", accept=ACCEPT),
        "acceptance tests": section("Phase 3.2: The second half"),
    }
    for name, last in cases.items():
        assert split_problems(PHASE, "3", FIRST + last) == [
            f"The split's last phase must keep the phase's {name} unchanged."], name


def test_only_the_last_part_may_have_acceptance_tests():
    first = section("Phase 3.1: The first half", criterion="the first half works", gate="pytest -q tests/a",
                    accept=("tests/test_other_contract.py", "def test_other():\n    assert True\n"))
    assert split_problems(PHASE, "3", first + LAST) == [
        "Split phase 1 has acceptance tests; only the last phase may, and only the original ones."]


# --- advisor_prompt ----------------------------------------------------------------------


def test_advisor_prompt_states_the_stall_in_order():
    s = stall(progress="Done: half of it", gate_report="Gate command failed: `pytest -q`",
              diff_stat=" a.py | 3 +++")
    text = advisor_prompt(s, ["amend", "stop"])
    assert "Read, Grep and Glob" in text
    marks = [s.reason, "<phase>", "<the design excerpt for phase 3>", "<progress>", "Done: half of it",
             "<gate_report>", "Gate command failed", "<uncommitted>", "a.py | 3 +++", s.log]
    positions = [text.index(m) for m in marks]
    assert positions == sorted(positions)


def test_advisor_prompt_says_when_a_part_of_the_stall_is_empty():
    text = advisor_prompt(stall(), ["amend", "stop"])
    assert "(none)" in text and "(nothing uncommitted)" in text


def test_advisor_prompt_names_only_the_offered_actions():
    every = advisor_prompt(stall(), list(ACTIONS))
    some = advisor_prompt(stall(), ["amend", "stop"])
    assert "too big for one context" in every and "A second call makes the edit" in every
    assert "too big for one context" not in some and "A second call makes the edit" not in some
    assert "lacked a fact" in some and "the stall needs the person" in some


# --- advise, through tests/fake_claude.py ------------------------------------------------


def answer(path, output):
    """A `claude -p` result shaped like the captured one, with `output` as its structured output."""
    doc = json.loads((FIXTURES / "claude_read_tools.json").read_text(encoding="utf-8"))
    doc["structured_output"] = output
    path.write_text(json.dumps(doc), encoding="utf-8")


def use_fake(monkeypatch, tmp_path, fake_claude, reply):
    cfg = tmp_path / "styre.json"
    cfg.write_text(json.dumps({"frontier": {"command": ["claude"], "timeout": 60}}), encoding="utf-8")
    monkeypatch.setenv("STYRE_CONFIG", str(cfg))
    monkeypatch.setenv("PATH", fake_claude)
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "calls.log"))
    monkeypatch.setenv("FAKE_CLAUDE_REPLY", str(reply))
    for var in ("FAKE_CLAUDE_EXIT", "FAKE_CLAUDE_SLEEP"):
        monkeypatch.delenv(var, raising=False)


def calls(tmp_path):
    log = tmp_path / "calls.log"
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def run_advise(tmp_path, actions):
    return advise(stall(), actions, cwd=str(tmp_path), timeline=Timeline(tmp_path / "timeline.jsonl"),
                  log_dir=tmp_path / "logs")


def test_advise_returns_a_good_answer_from_one_call(monkeypatch, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    replies.mkdir()
    answer(replies / "1.json", {"action": "amend", "reason": "It lacked the format.", "text": "Use JSON."})
    use_fake(monkeypatch, tmp_path, fake_claude, replies)
    advice, error = run_advise(tmp_path, ["amend", "stop"])
    assert error is None
    assert (advice.action, advice.text) == ("amend", "Use JSON.")
    made = calls(tmp_path)
    assert len(made) == 1
    argv = made[0]["argv"]
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == schema(["amend", "stop"])
    assert made[0]["stdin"] == advisor_prompt(stall(), ["amend", "stop"])
    lines = (tmp_path / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
    assert [e["role"] for e in map(json.loads, lines) if e["event"] == "model_call"] == ["advisor"]


def test_a_refused_answer_gets_one_retry_with_the_problems(monkeypatch, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    replies.mkdir()
    answer(replies / "1.json", {"action": "split", "reason": "Too big.", "text": FIRST + LAST})
    answer(replies / "2.json", {"action": "stop", "reason": "The design is wrong.", "text": ""})
    use_fake(monkeypatch, tmp_path, fake_claude, replies)
    advice, error = run_advise(tmp_path, ["amend", "stop"])
    assert error is None and advice.action == "stop"
    first, second = (c["stdin"] for c in calls(tmp_path))
    assert second.startswith(first)
    assert "Your advice was refused:\nThe advice's action must be one of: amend, stop." in second


def test_a_second_refusal_returns_the_first_problem(monkeypatch, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    replies.mkdir()
    for k in (1, 2):
        answer(replies / f"{k}.json", {"action": "patch", "reason": "r", "text": "t"})
    use_fake(monkeypatch, tmp_path, fake_claude, replies)
    advice, error = run_advise(tmp_path, ["amend", "stop"])
    assert advice is None
    assert error == "The advice's action must be one of: amend, stop."
    assert len(calls(tmp_path)) == 2


def test_a_failed_call_returns_its_sentence_without_a_retry(monkeypatch, tmp_path, fake_claude):
    use_fake(monkeypatch, tmp_path, fake_claude, tmp_path / "no-reply.json")
    advice, error = run_advise(tmp_path, ["amend", "stop"])
    assert advice is None
    assert error == "The advisor call printed output that is not JSON."
    assert len(calls(tmp_path)) == 1
