"""Acceptance: a stall goes to the advisor, which can amend or stop (M4 phase 2).

The whole loop runs against tests/fake_pi.py and tests/fake_claude.py; no test calls a model.
"""
import inspect
import json
from pathlib import Path

from conftest import DESIGN

from styre.design import parse_phases
from styre.gitops import diff_stat
from styre.prompts import advice_prompt
from styre.rundir import RunDir
from styre.runner import PhaseResult, run_phase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BLOCKED = "BLOCKED: the design does not say which format to use"
NOT_JSON = "The advisor call printed output that is not JSON."
STOP = {"action": "stop", "reason": "The design must name the format.", "text": ""}
AMEND = {"action": "amend", "reason": "The builder lacked the format.", "text": "Use JSON for the format."}


def run_dir(repo):
    name = (repo / ".styre" / "latest.txt").read_text(encoding="utf-8").strip()
    return repo / ".styre" / "runs" / name


def timeline(repo):
    lines = (run_dir(repo) / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(ln) for ln in lines]


def events(repo, kind):
    return [e for e in timeline(repo) if e["event"] == kind]


def stopped(repo):
    return events(repo, "run_end")[-1]["stopped"]


def answer(path, output):
    """A `claude -p` result shaped like the captured one, with `output` as its structured output."""
    doc = json.loads((FIXTURES / "claude_read_tools.json").read_text(encoding="utf-8"))
    doc["structured_output"] = output
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def advisor_env(tmp_path, reply):
    """The advisor's settings and the fake's files, all outside the repository."""
    cfg = tmp_path / "advisor-styre.json"
    cfg.write_text(json.dumps({"frontier": {"command": ["claude"], "timeout": 60}}), encoding="utf-8")
    return {"STYRE_CONFIG": str(cfg), "FAKE_CLAUDE_LOG": str(tmp_path / "advisor-calls.log"),
            "FAKE_CLAUDE_REPLY": str(reply)}


def calls(tmp_path):
    log = tmp_path / "advisor-calls.log"
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def offered(call):
    argv = call["argv"]
    return json.loads(argv[argv.index("--json-schema") + 1])["properties"]["action"]["enum"]


def attached(argv):
    return [a[1:].rsplit("/", 1)[-1] for a in argv if a.startswith("@")]


def pi_argvs(repo):
    text = (run_dir(repo) / "pi-argv.jsonl").read_text(encoding="utf-8")
    return [json.loads(ln) for ln in text.splitlines()]


def summary(repo):
    return (run_dir(repo) / "summary.md").read_text(encoding="utf-8")


# --- the interfaces ----------------------------------------------------------------------


def test_phase_result_holds_the_verdict_and_the_counters():
    result = PhaseResult(reason=None, stall=False, gate_report="", rounds=0, relays=0)
    assert (result.reason, result.stall, result.gate_report, result.rounds, result.relays) == (
        None, False, "", 0, 0)


def test_run_phase_takes_advice_and_after():
    params = inspect.signature(run_phase).parameters
    assert params["advice"].default is None and params["after"].default is None


def test_the_advice_prompt_file_is_named_after_the_phase():
    assert RunDir(Path("r")).advice(2) == Path("r") / "phase2.advice.md"


def test_advice_prompt_holds_the_advice_and_the_progress_file():
    phase = parse_phases(DESIGN)[0]
    text = advice_prompt(1, phase, "Use JSON for the format.", "Done: ran phase1.prompt.md")
    assert text.index("<advice>") < text.index("Use JSON for the format.") < text.index("</advice>")
    assert "<your_progress_file>" in text and "Done: ran phase1.prompt.md" in text


def test_diff_stat_lists_the_uncommitted_work(repo, monkeypatch):
    monkeypatch.chdir(repo)
    (repo / "work1.py").write_text("value = 1\n", encoding="utf-8")
    assert "work1.py" in diff_stat()


# --- the run -----------------------------------------------------------------------------


def test_a_stall_asks_the_advisor_once_and_its_stop_ends_the_run(styre, repo, commits, tmp_path,
                                                                 fake_claude):
    reply = answer(tmp_path / "stop.json", STOP)
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "blocked"},
              env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits() == ["initial"]
    assert stopped(repo) == (f"Stopped at phase 1: {BLOCKED}. The advisor stopped it: "
                             "The design must name the format. Work is left uncommitted.")
    made = calls(tmp_path)
    assert len(made) == 1
    assert {"amend", "stop"} <= set(offered(made[0]))  # later phases offer more
    assert BLOCKED in made[0]["stdin"] and "Do the first thing." in made[0]["stdin"]
    assert [(e["phase"], e["action"], e["reason"]) for e in events(repo, "advice")] == [
        (1, "stop", "The design must name the format.")]
    assert "- the advisor chose stop: The design must name the format." in summary(repo)


def test_amend_runs_the_phase_again_from_the_advice_file_and_commits(styre, repo, commits, tmp_path,
                                                                     fake_claude):
    reply = answer(tmp_path / "amend.json", AMEND)
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "blocked", "phase1.advice.md": "ok"},
              env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:2] == ["Phase 2: Second phase", "Phase 1: First phase"]
    text = (run_dir(repo) / "phase1.advice.md").read_text(encoding="utf-8")
    assert "<advice>" in text and "Use JSON for the format." in text
    assert "Done: ran phase1.prompt.md" in text  # the progress file was not cleared
    advised = [a for a in pi_argvs(repo) if "phase1.advice.md" in attached(a)]
    assert [attached(a) for a in advised] == [["phase1.prompt.md", "phase1.advice.md"]]
    steps = [e["step"] for e in events(repo, "pi_end") if e["phase"] == 1]
    assert steps == ["builder", "advised"]
    assert len(calls(tmp_path)) == 1
    assert "- the advisor chose amend: The builder lacked the format." in summary(repo)


def test_a_second_stall_of_the_phase_stops_without_a_second_call(styre, repo, commits, tmp_path,
                                                                 fake_claude):
    reply = answer(tmp_path / "amend.json", AMEND)
    r = styre("run", "design.md", "--quiet",
              plan={"phase1.prompt.md": "blocked", "phase1.advice.md": "blocked"},
              env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits() == ["initial"]
    assert stopped(repo) == (f"Stopped at phase 1: {BLOCKED}, after the advisor's amend. "
                             "Work is left uncommitted.")
    assert len(calls(tmp_path)) == 1
    assert len(events(repo, "advice")) == 1


def test_a_failed_advisor_call_stops_with_the_reason_and_the_calls_sentence(styre, repo, commits,
                                                                            tmp_path, fake_claude):
    env = advisor_env(tmp_path, tmp_path / "no-reply.json")  # missing: the fake prints nothing
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "blocked"}, env_extra=env)
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits() == ["initial"]
    assert stopped(repo) == (f"Stopped at phase 1: {BLOCKED}. The advisor could not be asked: "
                             f"{NOT_JSON} Work is left uncommitted.")
    assert [(e["action"], e["error"]) for e in events(repo, "advice")] == [(None, NOT_JSON)]
    assert f"- the advisor could not be asked: {NOT_JSON}" in summary(repo)


def test_a_host_failure_never_reaches_the_advisor(styre, repo, commits, tmp_path, fake_claude):
    reply = answer(tmp_path / "amend.json", AMEND)
    r = styre("run", "design.md", "--quiet", default="crash", env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 1, r.stdout + r.stderr
    assert stopped(repo) == "Stopped at phase 1: pi exited with 3. Work is left uncommitted."
    assert calls(tmp_path) == []
    assert events(repo, "advice") == []


def test_the_amended_attempt_continues_the_fix_round_numbers(styre, repo, commits, tmp_path,
                                                             fake_claude):
    reply = answer(tmp_path / "amend.json", AMEND)
    plan = {"phase1.prompt.md": "bad_gate", "phase1.fix1.md": "bad_gate", "phase1.fix2.md": "bad_gate",
            "phase1.advice.md": "bad_gate", "phase1.fix3.md": "ok"}
    r = styre("run", "design.md", "--quiet", plan=plan, env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:2] == ["Phase 2: Second phase", "Phase 1: First phase"]
    assert all((run_dir(repo) / f"phase1.fix{k}.md").exists() for k in (1, 2, 3))
    stdin = calls(tmp_path)[0]["stdin"]
    assert "<gate_report>" in stdin and "Gate command failed: `test -f done.txt`" in stdin
    assert "<uncommitted>" in stdin and "work1.py" in stdin


def test_preflight_warns_when_the_advisor_command_is_not_on_path(styre, repo, tmp_path):
    cfg = tmp_path / "missing-claude.json"
    cfg.write_text(json.dumps({"frontier": {"command": ["no-such-claude-m4"], "timeout": 60}}),
                   encoding="utf-8")
    r = styre("run", "design.md", "--quiet", env_extra={"STYRE_CONFIG": str(cfg)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert ("[warn] Claude Code ('no-such-claude-m4') is not on PATH: a stall will stop the run "
            "instead of going to the advisor.") in r.stdout + r.stderr


def test_a_broken_styre_json_stops_preflight(styre, repo, commits, tmp_path):
    cfg = tmp_path / "broken.json"
    cfg.write_text("{ not json", encoding="utf-8")
    r = styre("run", "design.md", "--quiet", env_extra={"STYRE_CONFIG": str(cfg)})
    assert r.returncode == 1
    assert f"Settings file {cfg} is not valid JSON" in r.stderr
    assert commits() == ["initial"]
