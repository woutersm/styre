"""Acceptance: the advisor's patch (M4 phase 3).

The whole loop runs against tests/fake_pi.py and tests/fake_claude.py; no test calls a model.
"""
import json
import subprocess
from pathlib import Path

from conftest import DESIGN

from styre.advisor import PATCH_SCHEMA, PATCH_TOOLS, Advice, Stall, patch
from styre.design import parse_phases
from styre.prompts import patch_prompt
from styre.timeline import Timeline

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FENCE = "`" * 3
NOT_JSON = "The advisor call printed output that is not JSON."
PATCH_ADVICE = {"action": "patch", "reason": "One hard part.", "text": "Create done.txt."}
EDIT_TOOLS = "Read,Grep,Glob,Edit,Write,Bash"


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def edit(replies, k, name, text):
    """What the fake's call k writes into its working directory before it answers."""
    target = replies / f"{k}.files" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def advisor_env(tmp_path, reply):
    """The advisor's settings and the fake's files, all outside the repository."""
    cfg = tmp_path / "advisor-styre.json"
    cfg.write_text(json.dumps({"frontier": {"command": ["claude"], "timeout": 60}}), encoding="utf-8")
    return {"STYRE_CONFIG": str(cfg), "FAKE_CLAUDE_LOG": str(tmp_path / "advisor-calls.log"),
            "FAKE_CLAUDE_REPLY": str(reply)}


def use_fake(monkeypatch, tmp_path, fake_claude, reply):
    for name, value in advisor_env(tmp_path, reply).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PATH", fake_claude)
    for var in ("FAKE_CLAUDE_EXIT", "FAKE_CLAUDE_SLEEP"):
        monkeypatch.delenv(var, raising=False)


def calls(tmp_path):
    log = tmp_path / "advisor-calls.log"
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def flag(call, name):
    argv = call["argv"]
    return argv[argv.index(name) + 1]


def offered(call):
    return json.loads(flag(call, "--json-schema"))["properties"]["action"]["enum"]


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def use_design(repo, text):
    (repo / "design.md").write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "brief"], cwd=repo, check=True)


def make_stall():
    return Stall(n="1", phase=parse_phases(DESIGN)[0], context="<the design excerpt for phase 1>",
                 reason="gate failed: test -f done.txt, still failing after 0 fix rounds",
                 progress="", gate_report="", diff_stat="", log=".styre/runs/r/logs/phase1.log")


ADVICE = Advice(action="patch", reason="One hard part.", text="Create done.txt in the root.", phases=[])


# --- the interfaces ----------------------------------------------------------------------


def test_the_patch_call_constants():
    assert PATCH_TOOLS == ["Read", "Grep", "Glob", "Edit", "Write", "Bash"]
    assert PATCH_SCHEMA == {"type": "object", "properties": {"summary": {"type": "string"}},
                            "required": ["summary"], "additionalProperties": False}


def test_patch_prompt_holds_the_diagnosis_the_phase_and_its_gate():
    text = patch_prompt(make_stall(), "Create done.txt in the root.")
    assert text.index("<diagnosis>") < text.index("Create done.txt in the root.") < text.index("</diagnosis>")
    assert "<the design excerpt for phase 1>" in text
    assert "test -f done.txt" in text


def test_patch_edits_through_the_fake_and_returns_none(monkeypatch, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    answer(replies / "1.json", {"summary": "Wrote done.txt."})
    edit(replies, 1, "done.txt", "done\n")
    work = tmp_path / "work"
    work.mkdir()
    use_fake(monkeypatch, tmp_path, fake_claude, replies)
    error = patch(make_stall(), ADVICE, cwd=str(work), timeline=Timeline(tmp_path / "timeline.jsonl"),
                  log_dir=tmp_path / "logs")
    assert error is None
    assert (work / "done.txt").read_text(encoding="utf-8") == "done\n"
    (call,) = calls(tmp_path)
    assert flag(call, "--tools") == EDIT_TOOLS
    assert json.loads(flag(call, "--json-schema")) == PATCH_SCHEMA
    assert call["stdin"] == patch_prompt(make_stall(), "Create done.txt in the root.")


def test_a_failed_patch_call_returns_its_sentence_and_is_not_retried(monkeypatch, tmp_path, fake_claude):
    use_fake(monkeypatch, tmp_path, fake_claude, tmp_path / "no-reply.json")
    error = patch(make_stall(), ADVICE, cwd=str(tmp_path), timeline=Timeline(tmp_path / "timeline.jsonl"),
                  log_dir=tmp_path / "logs")
    assert error == NOT_JSON
    assert len(calls(tmp_path)) == 1


# --- the run -----------------------------------------------------------------------------


def test_a_green_patch_commits_the_phase_with_the_trailer(styre, repo, commits, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    answer(replies / "1.json", PATCH_ADVICE)
    answer(replies / "2.json", {"summary": "Wrote done.txt."})
    edit(replies, 2, "done.txt", "done\n")
    r = styre("run", "design.md", "--quiet", "--retries", "0", plan={"phase1.prompt.md": "bad_gate"},
              env_extra=advisor_env(tmp_path, replies))
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:2] == ["Phase 2: Second phase", "Phase 1: First phase"]
    body = git(repo, "log", "-1", "--format=%B", "HEAD~1")
    assert body.strip() == "Phase 1: First phase\n\nStyre-Advisor: patch"
    assert "Claude" not in body and "Anthropic" not in body
    decide, change = calls(tmp_path)
    assert flag(decide, "--tools") == "Read,Grep,Glob" and "patch" in offered(decide)
    assert flag(change, "--tools") == EDIT_TOOLS
    assert [e["patch"] for e in events(repo, "commit") if e["phase"] == 1] == [True]
    assert [e["status"] for e in events(repo, "phase_end") if e["phase"] == 1][-1] == "committed"
    assert [e["command"] for e in events(repo, "gate_end") if e.get("step") == "patch"] == [
        "test -f done.txt"]
    assert not (run_dir(repo) / "phase1.fix1.md").exists()
    summary = (run_dir(repo) / "summary.md").read_text(encoding="utf-8")
    assert "committed (patch)" in summary
    assert "- the advisor patched it: the commit carries Styre-Advisor: patch" in summary


def test_a_red_patch_stops_the_run_and_commits_nothing(styre, repo, commits, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    answer(replies / "1.json", PATCH_ADVICE)
    answer(replies / "2.json", {"summary": "Changed nothing useful."})  # no 2.files: done.txt stays missing
    r = styre("run", "design.md", "--quiet", "--retries", "0", plan={"phase1.prompt.md": "bad_gate"},
              env_extra=advisor_env(tmp_path, replies))
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits() == ["initial"]
    assert stopped(repo).startswith("Stopped at phase 1: gate failed: test -f done.txt")
    assert stopped(repo).endswith("The advisor's patch left the gate red: gate failed: test -f done.txt "
                                  "Work is left uncommitted.")
    assert [e["step"] for e in events(repo, "pi_end") if e["phase"] == 1] == ["builder"]
    assert len(calls(tmp_path)) == 2


def test_a_failed_patch_call_stops_the_run(styre, repo, commits, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    answer(replies / "1.json", PATCH_ADVICE)  # no 2.json: the patch call prints nothing
    r = styre("run", "design.md", "--quiet", "--retries", "0", plan={"phase1.prompt.md": "bad_gate"},
              env_extra=advisor_env(tmp_path, replies))
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits() == ["initial"]
    assert stopped(repo).endswith(f"The advisor's patch call failed: {NOT_JSON} Work is left uncommitted.")


def three_phase_design():
    lines = ["# Three phases", "", "Preamble every phase needs.", ""]
    for n, name in ((1, "One"), (2, "Two"), (3, "Three")):
        lines += [f"## Phase {n}: {name}", f"Make p{n}.txt.", "", "### Exit criteria", f"- p{n}.txt exists",
                  "", "### Gate", FENCE, f"test -f p{n}.txt", FENCE, ""]
    return "\n".join(lines) + "\n"


def test_after_two_patches_patch_is_no_longer_offered(styre, repo, commits, tmp_path, fake_claude):
    use_design(repo, three_phase_design())
    replies = tmp_path / "replies"
    for k, n in ((1, 1), (3, 2)):
        answer(replies / f"{k}.json", PATCH_ADVICE)
        answer(replies / f"{k + 1}.json", {"summary": f"Wrote p{n}.txt."})
        edit(replies, k + 1, f"p{n}.txt", f"{n}\n")
    answer(replies / "5.json", {"action": "stop", "reason": "Two patches are enough.", "text": ""})
    r = styre("run", "design.md", "--quiet", "--retries", "0", default="bad_gate",
              env_extra=advisor_env(tmp_path, replies))
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits()[:2] == ["Phase 2: Two", "Phase 1: One"]
    made = calls(tmp_path)
    assert len(made) == 5
    assert "patch" in offered(made[0]) and "patch" in offered(made[2])
    assert "patch" not in offered(made[4]) and {"amend", "stop"} <= set(offered(made[4]))
