"""Acceptance: the advisor's split (M4 phase 4).

The whole loop runs against tests/fake_pi.py and tests/fake_claude.py; no test calls a model.
"""
import inspect
import json
import subprocess
from pathlib import Path

from conftest import DESIGN

from styre.rundir import RunDir
from styre.runner import run_phase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FENCE = "`" * 3
BLOCKED = "BLOCKED: the design does not say which format to use"
CONTRACT_PATH = "tests/test_phase1_contract.py"
CONTRACT = "def test_phase1_contract():\n    assert True\n"


def section(title, criterion, gate, accept=None):
    """One phase section in the design format, built line by line."""
    lines = ["## " + title, "Build this part.", ""]
    if accept is not None:
        lines += ["### Acceptance tests", "", f"`{accept[0]}`", FENCE + "python", accept[1] + FENCE, ""]
    lines += ["### Exit criteria", f"- {criterion}", "", "### Gate", FENCE, gate, FENCE, ""]
    return "\n".join(lines) + "\n"


# The last part keeps phase 1's criterion and gate from tests/conftest.py's DESIGN.
SPLIT = (section("Phase 1.1: First half", "work1.py exists", "test -f work1.py")
         + section("Phase 1.2: Second half", "done.txt exists", "test -f done.txt"))
TITLES = ["Phase 1.1: First half", "Phase 1.2: Second half"]
CONTRACT_SPLIT = (section("Phase 1.1: Prepare", "the contract file is not in the tree",
                          "test ! -f " + CONTRACT_PATH)
                  + section("Phase 1.2: Finish", "done.txt exists", "test -f done.txt",
                            accept=(CONTRACT_PATH, CONTRACT)))


def contract_design():
    """The conftest design with an acceptance test in phase 1."""
    return DESIGN.replace(
        "### Exit criteria\n- done.txt exists\n",
        "### Acceptance tests\n\n`" + CONTRACT_PATH + "`\n" + FENCE + "python\n" + CONTRACT + FENCE
        + "\n\n### Exit criteria\n- done.txt exists\n")


def run_dir(repo):
    name = (repo / ".styre" / "latest.txt").read_text(encoding="utf-8").strip()
    return repo / ".styre" / "runs" / name


def events(repo, kind):
    lines = (run_dir(repo) / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, lines) if e["event"] == kind]


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


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def use_design(repo, text):
    (repo / "design.md").write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "brief"], cwd=repo, check=True)


# --- the interfaces ----------------------------------------------------------------------


def test_run_phase_takes_a_part():
    assert inspect.signature(run_phase).parameters["part"].default is None


def test_a_part_prompt_file_is_named_after_the_phase_and_the_part():
    assert RunDir(Path("r")).split(1, 2) == Path("r") / "phase1.split2.md"


# --- the run -----------------------------------------------------------------------------


def test_a_two_part_split_commits_each_part_in_order(styre, repo, commits, tmp_path, fake_claude):
    reply = answer(tmp_path / "split.json",
                   {"action": "split", "reason": "Too big for one context.", "text": SPLIT})
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "blocked"},
              env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:3] == ["Phase 2: Second phase", "Phase 1.2: Second half", "Phase 1.1: First half"]
    made = calls(tmp_path)
    assert len(made) == 1 and offered(made[0]) == ["amend", "split", "patch", "stop"]
    assert [(e["action"], e["titles"]) for e in events(repo, "advice")] == [("split", TITLES)]
    names = [attached(a) for a in pi_argvs(repo)]
    assert ["phase1.split1.md", "phase1.advice.md"] in names and ["phase1.split2.md"] in names
    steps = [e["step"] for e in events(repo, "pi_end") if e["phase"] == 1]
    assert steps == ["builder", "split 1", "split 2"]
    gates = [(e["step"], e["command"]) for e in events(repo, "gate_end") if e["phase"] == 1]
    assert gates == [("split 1", "test -f work1.py"), ("split 2", "test -f done.txt")]
    d = run_dir(repo)
    one = (d / "phase1.split1.md").read_text(encoding="utf-8")
    assert "- Phase 1.1: First half  <- yours" in one and "- Phase 2: Second phase" in one
    assert "<notes_from_the_previous_phase>\n(none)" in one
    assert "Notes from phase 1." in (d / "phase1.split2.md").read_text(encoding="utf-8")
    assert "Notes from phase 1." in (d / "phase2.prompt.md").read_text(encoding="utf-8")
    assert "you build part 1 of 2" in (d / "phase1.advice.md").read_text(encoding="utf-8")
    summary = (d / "summary.md").read_text(encoding="utf-8")
    assert "- the advisor split it into: Phase 1.1: First half; Phase 1.2: Second half" in summary


def test_only_the_last_part_runs_with_the_phase_acceptance_tests(styre, repo, commits, tmp_path,
                                                                 fake_claude):
    use_design(repo, contract_design())
    reply = answer(tmp_path / "split.json",
                   {"action": "split", "reason": "Too big for one context.", "text": CONTRACT_SPLIT})
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "blocked"},
              env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:3] == ["Phase 2: Second phase", "Phase 1.2: Finish", "Phase 1.1: Prepare"]
    assert git(repo, "show", f"HEAD~1:{CONTRACT_PATH}") == CONTRACT
    assert CONTRACT_PATH not in git(repo, "show", "--name-only", "--format=", "HEAD~2")


def test_a_stalled_part_stops_the_run_without_a_second_call(styre, repo, commits, tmp_path, fake_claude):
    reply = answer(tmp_path / "split.json",
                   {"action": "split", "reason": "Too big for one context.", "text": SPLIT})
    r = styre("run", "design.md", "--quiet",
              plan={"phase1.prompt.md": "blocked", "phase1.advice.md": "blocked"},
              env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits() == ["initial"]
    assert stopped(repo) == (f"Stopped at phase 1 (Phase 1.1: First half): {BLOCKED}, after the "
                             "advisor's split. Work is left uncommitted.")
    assert len(calls(tmp_path)) == 1
