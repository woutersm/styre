"""The advisor's checks and call (styre/advisor.py).

Each sentence `check()` and `split_problems()` return, and `advise()`'s good answer,
retry and failed call through tests/fake_claude.py. No test calls a real model.
"""
import json
from pathlib import Path

from styre.advisor import ACTIONS, Advice, Stall, advise, check, schema, split_problems
from styre.design import parse_phases
from styre.prompts import advisor_prompt
from styre.timeline import Timeline

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FENCE = "`" * 3
ACCEPT = ("tests/test_thing_contract.py", "def test_thing_contract():\n    assert True\n")


def section(title, criterion="the thing works", gate="pytest -q", accept=None):
    lines = ["## " + title, "Build it.", ""]
    if accept is not None:
        lines += ["### Acceptance tests", "", f"`{accept[0]}`", FENCE + "python",
                  accept[1] + FENCE, ""]
    lines += ["### Exit criteria", f"- {criterion}", "", "### Gate", FENCE, gate, FENCE, ""]
    return "\n".join(lines) + "\n"


PHASE = parse_phases(section("Phase 3: Build the thing", accept=ACCEPT))[0]
FIRST = section("Phase 3.1: The first half", criterion="the first half works",
                gate="pytest -q tests/a")
LAST = section("Phase 3.2: The second half", accept=ACCEPT)
GOOD_SPLIT = FIRST + LAST


def stall(**changes):
    fields = {"n": "3", "phase": PHASE, "context": "<the design excerpt for phase 3>",
              "reason": "gate failed: pytest -q", "progress": "", "gate_report": "",
              "diff_stat": "", "log": ".styre/runs/r/logs/phase3.log"}
    fields.update(changes)
    return Stall(**fields)


def good(answer):
    advice, problems = check(answer, stall(), list(ACTIONS))
    assert problems == []
    return advice


def test_check_good_amend_and_stop():
    advice = good({"action": "amend", "reason": "It lacked the format.", "text": "Use JSON."})
    assert isinstance(advice, Advice)
    assert (advice.action, advice.reason, advice.text, advice.phases) == (
        "amend", "It lacked the format.", "Use JSON.", [])
    assert good({"action": "stop", "reason": "The design is wrong.", "text": ""}).action == "stop"
    assert good({"action": "patch", "reason": "r", "text": "Fix the parser."}).text == "Fix the parser."


def test_check_action_not_offered_names_only_those_offered():
    for actions, answer in [
            (["amend", "stop"], {"action": "split", "reason": "r", "text": "t"}),
            (["stop"], {"action": "amend", "reason": "r", "text": "t"}),
            ([], {"action": "stop", "reason": "r", "text": ""})]:
        advice, problems = check(answer, stall(), actions)
        assert advice is None
        assert problems == [f"The advice's action must be one of: {', '.join(actions)}."], actions


def test_check_every_refusal_sentence():
    for name, answer, sentence, actions in [
            ("not a dict", "stop", "The advice's action must be one of: amend, stop.",
             ["amend", "stop"]),
            ("blank reason", {"action": "stop", "reason": "  ", "text": ""},
             "The advice has no reason.", list(ACTIONS)),
            ("missing reason", {"action": "stop", "text": ""}, "The advice has no reason.",
             list(ACTIONS)),
            ("amend no text", {"action": "amend", "reason": "r", "text": ""},
             "The advice's text is empty; amend, split and patch need it.", list(ACTIONS)),
            ("split no text", {"action": "split", "reason": "r", "text": ""},
             "The advice's text is empty; amend, split and patch need it.", list(ACTIONS)),
            ("patch no text", {"action": "patch", "reason": "r", "text": ""},
             "The advice's text is empty; amend, split and patch need it.", list(ACTIONS)),
            ("missing text", {"action": "amend", "reason": "r"},
             "The advice's text is empty; amend, split and patch need it.", list(ACTIONS)),
            ("one-phase split", {"action": "split", "reason": "r",
                                 "text": LAST.replace("Phase 3.2:", "Phase 3.1:")},
             "The split has 1 phase; it must have 2 or 3.", list(ACTIONS)),
            ("wrong part title", {"action": "split", "reason": "r",
                                  "text": FIRST + LAST.replace("Phase 3.2:", "Phase 3.3:")},
             "Split phase 2's title must start with 'Phase 3.2:'.", list(ACTIONS)),
            ("part without gate", {"action": "split", "reason": "r",
                                   "text": ("## Phase 3.1: No gate\nBuild it.\n\n"
                                            "### Exit criteria\n- it works\n\n") + LAST},
             "Phase 1 has no '### Gate' code block.", list(ACTIONS)),
            ("part without criteria", {"action": "split", "reason": "r",
                                       "text": ("## Phase 3.1: No criteria\nBuild it.\n\n"
                                                "### Gate\n````\npytest -q tests/a\n````\n\n") + LAST},
             "Phase 1 has no '### Exit criteria' list.", list(ACTIONS)),
            ("last gate changed", {"action": "split", "reason": "r",
                                   "text": FIRST + section("Phase 3.2: The second half",
                                                           gate="pytest -q tests/b", accept=ACCEPT)},
             "The split's last phase must keep the phase's gate unchanged.", list(ACTIONS)),
            ("last criteria changed", {"action": "split", "reason": "r",
                                       "text": FIRST + section("Phase 3.2: The second half",
                                                               criterion="something else",
                                                               accept=ACCEPT)},
             "The split's last phase must keep the phase's exit criteria unchanged.",
             list(ACTIONS)),
            ("last acceptance changed", {"action": "split", "reason": "r",
                                         "text": FIRST + section("Phase 3.2: The second half")},
             "The split's last phase must keep the phase's acceptance tests unchanged.",
             list(ACTIONS)),
            ("early acceptance", {"action": "split", "reason": "r",
                                  "text": section("Phase 3.1: The first half",
                                                  gate="pytest -q tests/a",
                                                  accept=("tests/test_other.py", "x = 1\n")) + LAST},
             "Split phase 1 has acceptance tests; only the last phase may, "
             "and only the original ones.", list(ACTIONS)),
    ]:
        advice, problems = check(answer, stall(), actions)
        assert advice is None, name
        assert sentence in problems, name


def test_split_problems_counts():
    for text, sentence in [
            (FIRST + LAST, None),
            (LAST.replace("Phase 3.2:", "Phase 3.1:"),
             "The split has 1 phase; it must have 2 or 3."),
            (FIRST + LAST + section("Phase 3.3: The third half"),
             "The split's last phase must keep the phase's acceptance tests unchanged.")]:
        problems = split_problems(PHASE, "3", text)
        if sentence is None:
            assert problems == []
        else:
            assert sentence in problems, text


def test_split_problems_keeps_the_original_sents_from_validate():
    # Both parts use the original acceptance path: validate's repeat sentence survives in the
    # split's problems, next to the split's own sentences.
    text = section("Phase 3.1: The first half", gate="pytest -q tests/a", accept=ACCEPT) \
        + section("Phase 3.2: The second half",
                  accept=("tests/test_thing_contract.py", "other\n"))
    problems = split_problems(PHASE, "3", text)
    assert "Phase 2 repeats the acceptance test path 'tests/test_thing_contract.py' " \
           "from phase 1." in problems
    assert "Split phase 1 has acceptance tests; only the last phase may, " \
           "and only the original ones." in problems


def test_split_problems_early_acceptance_is_name_1():
    first = section("Phase 3.1: The first half", gate="pytest -q tests/a",
                    accept=("tests/test_other.py", "x = 1\n"))
    assert split_problems(PHASE, "3", first + LAST) == [
        "Split phase 1 has acceptance tests; only the last phase may, and only the original ones."]


def test_good_split_parses_phases():
    advice = good({"action": "split", "reason": "Too big.", "text": GOOD_SPLIT})
    assert [p.title for p in advice.phases] == ["Phase 3.1: The first half",
                                                "Phase 3.2: The second half"]


# --- advise, through tests/fake_claude.py ------------------------------------------------


def answer(path, output):
    doc = json.loads((FIXTURES / "claude_read_tools.json").read_text(encoding="utf-8"))
    doc["structured_output"] = output
    path.write_text(json.dumps(doc), encoding="utf-8")


def use_fake(monkeypatch, tmp_path, fake_claude, reply):
    cfg = tmp_path / "styre.json"
    cfg.write_text(json.dumps({"frontier": {"command": ["claude"], "timeout": 60}}),
                   encoding="utf-8")
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


def run_advise(tmp_path, actions=("amend", "split", "stop")):
    return advise(stall(), list(actions), cwd=str(tmp_path),
                  timeline=Timeline(tmp_path / "timeline.jsonl"), log_dir=tmp_path / "logs")


def test_advise_good_answer_is_one_call(monkeypatch, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    replies.mkdir()
    answer(replies / "1.json", {"action": "split", "reason": "Too big.", "text": GOOD_SPLIT})
    use_fake(monkeypatch, tmp_path, fake_claude, replies)
    advice, error = run_advise(tmp_path, ("amend", "split", "stop"))
    assert error is None
    assert advice.action == "split"
    assert [p.title for p in advice.phases] == [
        "Phase 3.1: The first half", "Phase 3.2: The second half"]
    made = calls(tmp_path)
    assert len(made) == 1
    argv = made[0]["argv"]
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == schema(
        ["amend", "split", "stop"])
    assert made[0]["stdin"] == advisor_prompt(stall(), ["amend", "split", "stop"])


def test_advise_retry_then_good_answer(monkeypatch, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    replies.mkdir()
    answer(replies / "1.json", {"action": "patch", "reason": "r", "text": "t"})
    answer(replies / "2.json", {"action": "stop", "reason": "The design is wrong.", "text": ""})
    use_fake(monkeypatch, tmp_path, fake_claude, replies)
    advice, error = run_advise(tmp_path)
    assert error is None and advice.action == "stop"
    first, second = (c["stdin"] for c in calls(tmp_path))
    assert second.startswith(first)
    assert ("Your advice was refused:\n"
            "The advice's action must be one of: amend, split, stop.") in second


def test_advise_second_refusal_returns_the_first_problem(monkeypatch, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    replies.mkdir()
    for k in (1, 2):
        answer(replies / f"{k}.json", {"action": "split", "reason": "r",
                                       "text": LAST.replace("Phase 3.2:", "Phase 3.1:")})
    use_fake(monkeypatch, tmp_path, fake_claude, replies)
    advice, error = run_advise(tmp_path, ("amend", "split", "stop"))
    assert advice is None
    assert error == "The split has 1 phase; it must have 2 or 3."
    assert len(calls(tmp_path)) == 2


def test_advise_retry_call_failure_returns_its_sentence(monkeypatch, tmp_path, fake_claude):
    # The first answer is refused; the retry call itself fails and its sentence is returned.
    replies = tmp_path / "replies"
    replies.mkdir()
    answer(replies / "1.json", {"action": "split", "reason": "r", "text": "not phases"})
    use_fake(monkeypatch, tmp_path, fake_claude, replies)
    advice, error = run_advise(tmp_path)
    assert advice is None
    assert error == "The advisor call printed output that is not JSON."
    assert len(calls(tmp_path)) == 2
