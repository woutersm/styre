import json

from styre.state import read_state, state_problem


def test_read_state_tolerates_missing_and_mangled(tmp_path):
    assert read_state(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert read_state(bad) is None
    listy = tmp_path / "list.json"
    listy.write_text("[1, 2]", encoding="utf-8")
    assert read_state(listy) is None


def test_read_state_returns_the_object(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"status": "DONE"}), encoding="utf-8")
    assert read_state(p) == {"status": "DONE"}


def test_done_with_no_unmet_criteria_passes():
    assert state_problem({"status": "DONE", "unmet_criteria": []}) is None
    assert state_problem({"status": "done", "unmet_criteria": []}) is None


def test_done_with_unmet_criteria_is_contradictory():
    problem = state_problem({"status": "DONE", "unmet_criteria": ["the CLI reads stdin"]})
    assert "reported DONE but listed unmet criteria: the CLI reads stdin" == problem


def test_blocked_reports_its_reason():
    assert state_problem({"status": "BLOCKED", "reason": "no spec"}) == "BLOCKED: no spec"
    assert state_problem({"status": "BLOCKED"}) == "BLOCKED: no reason given"


def test_missing_or_odd_state_is_a_problem():
    assert state_problem(None) == "no state file written, or it was not valid JSON"
    assert state_problem({"status": "maybe"}) == "unexpected status 'maybe'"
    assert state_problem({"status": "DONE"}) == "state file has no unmet_criteria list"
