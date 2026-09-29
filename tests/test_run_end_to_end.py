"""The whole loop, driven by the fake pi on PATH (tests/fake_pi.py)."""
import json
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fixtures' gate uses `test -f`")


def run_dir(repo):
    """The run directory .styre/latest.txt points at."""
    name = (repo / ".styre" / "latest.txt").read_text(encoding="utf-8").strip()
    return repo / ".styre" / "runs" / name


def run_dirs(repo):
    return sorted(d.name for d in (repo / ".styre" / "runs").iterdir() if d.is_dir())


def test_happy_path_commits_one_per_phase(styre, repo, commits):
    r = styre("run", "design.md", "--quiet")
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:2] == ["Phase 2: Second phase", "Phase 1: First phase"]
    # The run's own report is summarize's, written as the run ends.
    summary = (run_dir(repo) / "summary.md").read_text(encoding="utf-8")
    assert summary.count("| committed |") == 2 and summary in r.stdout
    assert (repo / "AGENTS.md").exists()
    assert "## Phase 1" in (repo / "docs" / "decisions.md").read_text(encoding="utf-8")


def test_each_prompt_holds_the_preamble_and_only_its_own_phase(styre, repo, commits):
    styre("run", "design.md", "--quiet")
    one = (run_dir(repo) / "phase1.prompt.md").read_text(encoding="utf-8")
    two = (run_dir(repo) / "phase2.prompt.md").read_text(encoding="utf-8")
    assert "Preamble every phase needs." in one and "Preamble every phase needs." in two
    assert "- Phase 2: Second phase  <- yours" in two   # the index marks the phase at hand
    assert "Do the second thing." in two
    assert "Do the first thing." not in two             # earlier phases arrive as decisions


def test_the_decisions_log_is_committed_but_reaches_no_later_prompt(styre, repo, commits):
    styre("run", "design.md", "--quiet")
    log = (repo / "docs" / "decisions.md").read_text(encoding="utf-8")
    assert "## Phase 1: First phase" in log and "## Phase 2: Second phase" in log
    two = (run_dir(repo) / "phase2.prompt.md").read_text(encoding="utf-8")
    assert "Chose the obvious thing." not in two      # phase 1's decisions stay out
    assert "Notes from phase 1." in two               # its notes are the channel that carries


def test_the_run_branch_is_named_after_the_design(styre, repo, commits):
    styre("run", "design.md", "--quiet")
    head = (repo / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    assert head.endswith("refs/heads/overnight/design")


def test_a_failed_gate_is_fixed_and_then_committed(styre, repo, commits):
    r = styre("run", "design.md", "--quiet",
              plan={"phase1.prompt.md": "bad_gate", "phase1.fix1.md": "ok"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "fix round 1 of 2" in r.stdout
    assert commits()[:2] == ["Phase 2: Second phase", "Phase 1: First phase"]
    assert (run_dir(repo) / "phase1.fix1.md").exists()


def test_a_gate_that_never_goes_green_stops_the_run(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--retries", "1", default="bad_gate")
    assert r.returncode == 1
    assert commits() == ["initial"]
    assert "still failing after 1 fix rounds" in r.stdout


def test_the_test_guard_rejects_a_skip_marker(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--retries", "0", default="skip_test")
    assert r.returncode == 1
    assert "test guard: skipped or removed tests" in r.stdout
    assert commits() == ["initial"]


def test_allow_test_changes_turns_the_guard_off(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--retries", "0", "--allow-test-changes",
              default="skip_test")
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(commits()) == 3


def test_blocked_stops_the_run_with_the_reason(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "blocked"})
    assert r.returncode == 1
    assert "BLOCKED: the design does not say which format to use" in r.stdout
    assert commits() == ["initial"]


def test_done_with_unmet_criteria_is_rejected(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "lying"})
    assert r.returncode == 1
    assert "reported DONE but listed unmet criteria" in r.stdout
    assert "unmet criterion: the second criterion" in (
        run_dir(repo) / "summary.md").read_text(encoding="utf-8")


def test_a_phase_that_changes_nothing_is_not_committed(styre, repo, commits):
    # Phase 1 leaves done.txt committed, so phase 2's gate passes without it touching
    # anything. Phase 1 itself always stages at least AGENTS.md.
    r = styre("run", "design.md", "--quiet", plan={"phase2.prompt.md": "nochange"})
    assert r.returncode == 1
    assert "changed nothing (no staged diff)" in r.stdout
    assert commits()[0] == "Phase 1: First phase"


def test_an_empty_model_response_says_so_instead_of_blaming_the_agent(styre, repo, commits):
    """A provider that refuses the request and pi's agent ignoring its contract look
    identical from here: pi exits 0 and writes nothing either way. The zero-token usage
    block is what tells them apart, and it took two days to find without this message."""
    r = styre("run", "design.md", "--quiet", "--retries", "0", default="empty")
    assert r.returncode == 1
    assert "the model returned an empty response (0 tokens in and out)" in r.stdout
    assert "check the model host's log" in r.stdout
    assert commits() == ["initial"]


def test_a_crashing_agent_stops_the_run(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", default="crash")
    assert r.returncode == 1
    assert "pi exited with 3" in r.stdout


def test_a_hung_agent_times_out(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--timeout", "1", default="hang", timeout=90)
    assert r.returncode == 1
    assert "pi exited with 124 (timeout)" in r.stdout


def test_from_phase_resumes_without_rerunning_earlier_phases(styre, repo, commits):
    assert styre("run", "design.md", "--quiet").returncode == 0
    before = commits()
    r = styre("run", "design.md", "--quiet", "--from-phase", "2", "--allow-dirty")
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(commits()) == len(before) + 1
    # Phase 1 was not run again: the resumed invocation appends to the same timeline, and
    # phase 1 still has only the one pi step the first invocation gave it.
    steps = [e for e in timeline(repo) if e["event"] == "pi_end" and e["phase"] == 1]
    assert len(steps) == 1


def test_each_run_gets_its_own_directory(styre, repo, commits):
    assert styre("run", "design.md", "--quiet").returncode == 0
    first = run_dir(repo)
    assert styre("run", "design.md", "--quiet", "--allow-dirty").returncode == 0
    second = run_dir(repo)
    assert first != second and len(run_dirs(repo)) == 2
    # Nothing from the first run was overwritten, so the two can be compared.
    for d in (first, second):
        assert (d / "phase1.prompt.md").exists() and (d / "logs" / "phase1.events.jsonl").exists()
        assert (d / "summary.md").exists()


def test_the_agents_two_files_are_collected_into_the_run_directory(styre, repo, commits):
    styre("run", "design.md", "--quiet")
    d = run_dir(repo)
    state = json.loads((d / "phase1.state.json").read_text(encoding="utf-8"))
    assert state["status"] == "DONE"
    assert "Notes from phase 1." in (d / "phase1.notes-next.md").read_text(encoding="utf-8")
    # The drop box is emptied, so a later run cannot mistake a stale file for its own.
    assert not (repo / ".styre" / "phase1.state.json").exists()
    assert not (repo / ".styre" / "notes-next.md").exists()


def test_a_new_run_carries_no_notes_from_the_last_one(styre, repo, commits):
    styre("run", "design.md", "--quiet")
    styre("run", "design.md", "--quiet", "--allow-dirty", "--from-phase", "1")
    prompt = (run_dir(repo) / "phase1.prompt.md").read_text(encoding="utf-8")
    assert "<notes_from_the_previous_phase>\n(none)" in prompt


def test_resume_continues_in_the_latest_run_and_reads_its_notes(styre, repo, commits):
    assert styre("run", "design.md", "--quiet",
                 plan={"phase2.prompt.md": "blocked"}).returncode == 1
    first = run_dir(repo)
    r = styre("run", "design.md", "--quiet", "--from-phase", "2", "--allow-dirty")
    assert r.returncode == 0, r.stdout + r.stderr
    assert run_dir(repo) == first and len(run_dirs(repo)) == 1
    assert "Notes from phase 1." in (first / "phase2.prompt.md").read_text(encoding="utf-8")


def test_run_id_selects_an_older_run(styre, repo, commits):
    styre("run", "design.md", "--quiet")
    first = run_dir(repo)
    styre("run", "design.md", "--quiet", "--allow-dirty")
    r = styre("run", "design.md", "--quiet", "--allow-dirty", "--from-phase", "2",
              "--run-id", first.name)
    assert r.returncode == 0, r.stdout + r.stderr
    assert run_dir(repo) == first and len(run_dirs(repo)) == 2


def test_an_unknown_run_id_is_refused(styre, repo, commits):
    r = styre("run", "design.md", "--quiet", "--run-id", "nope")
    assert r.returncode == 1
    assert "No run directory .styre/runs/nope" in r.stderr
    assert commits() == ["initial"]


def timeline(repo):
    lines = (run_dir(repo) / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(ln) for ln in lines]


def test_the_timeline_records_the_whole_run(styre, repo, commits):
    assert styre("run", "design.md", "--quiet").returncode == 0
    events = timeline(repo)
    kinds = [e["event"] for e in events]
    assert kinds[0] == "run_start" and kinds[-1] == "run_end"
    assert kinds.count("phase_end") == 2 and kinds.count("commit") == 2
    assert kinds.count("pi_start") == kinds.count("pi_end") == 2
    assert kinds.count("gate_start") == kinds.count("gate_end") == 2

    start = events[0]
    assert start["branch"] == "overnight/design" and start["pi_version"] == "0.85.1-fake"
    assert start["phases"] == 2 and len(start["design_sha256"]) == 16 and start["templates"]

    pi_end = next(e for e in events if e["event"] == "pi_end")
    assert (pi_end["phase"], pi_end["step"], pi_end["rc"]) == (1, "builder", 0)
    assert pi_end["seconds"] >= 0
    gate = next(e for e in events if e["event"] == "gate_end")
    assert (gate["command"], gate["rc"]) == ("test -f done.txt", 0)
    assert next(e for e in events if e["event"] == "guard_result")["ok"] is True
    sha = next(e for e in events if e["event"] == "commit")["sha"]
    assert len(sha) == 40
    assert next(e for e in events if e["event"] == "phase_end")["status"] == "committed"
    assert events[-1] == {**events[-1], "exit_code": 0, "committed": 2, "stopped": None}


def test_the_timeline_records_a_fix_round_and_which_gate_failed(styre, repo, commits):
    styre("run", "design.md", "--quiet",
          plan={"phase1.prompt.md": "bad_gate", "phase1.fix1.md": "ok"})
    events = timeline(repo)
    steps = [(e["phase"], e["step"]) for e in events if e["event"] == "pi_end"]
    assert steps[:2] == [(1, "builder"), (1, "fix 1")]
    failed = [e for e in events if e["event"] == "gate_end" and e["rc"] != 0]
    assert [e["command"] for e in failed] == ["test -f done.txt"]
    assert next(e for e in events if e["event"] == "phase_end")["rounds"] == 1


def test_the_timeline_records_the_guard_verdict_and_the_stop(styre, repo, commits):
    styre("run", "design.md", "--quiet", "--retries", "0", default="skip_test")
    events = timeline(repo)
    guard = next(e for e in events if e["event"] == "guard_result")
    assert guard["ok"] is False and "skipped" in guard["problem"]
    phase = next(e for e in events if e["event"] == "phase_end")
    assert phase["status"] == "stopped" and "test guard" in phase["reason"]
    assert events[-1]["exit_code"] == 1 and events[-1]["committed"] == 0


def test_the_timeline_survives_a_run_killed_mid_phase(styre, repo, commits):
    styre("run", "design.md", "--quiet", "--timeout", "1", default="hang", timeout=90)
    events = timeline(repo)
    # No run_end for the phase that died is fine; the pair around pi must still be there.
    pi_end = next(e for e in events if e["event"] == "pi_end")
    assert pi_end["rc"] == 124


def test_a_resumed_run_appends_to_the_same_timeline(styre, repo, commits):
    styre("run", "design.md", "--quiet", plan={"phase2.prompt.md": "blocked"})
    first = len(timeline(repo))
    styre("run", "design.md", "--quiet", "--from-phase", "2", "--allow-dirty")
    events = timeline(repo)
    assert len(events) > first
    assert [e["event"] for e in events].count("run_start") == 2
    assert [e["from_phase"] for e in events if e["event"] == "run_start"] == [1, 2]


def test_each_pi_step_saves_its_session_under_the_run(styre, repo, commits):
    styre("run", "design.md", "--quiet", "--retries", "1",
          plan={"phase1.prompt.md": "bad_gate", "phase1.fix1.md": "ok"})
    d = run_dir(repo)
    one = sorted((d / "sessions" / "phase1").iterdir())
    assert len(one) == 2 and len(list((d / "sessions" / "phase2").iterdir())) == 1
    assert all(p.name.endswith(".jsonl") for p in one)
    names = [json.loads(p.read_text(encoding="utf-8").splitlines()[1])["name"] for p in one]
    assert sorted(names) == [f"{d.name} phase 1 builder", f"{d.name} phase 1 fix 1"]


def test_summarize_reports_the_run_that_just_happened(styre, repo, commits):
    styre("run", "design.md", "--quiet", "--retries", "1",
          plan={"phase1.prompt.md": "bad_gate", "phase1.fix1.md": "ok"})
    r = styre("summarize")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"# Run {run_dir(repo).name}" in r.stdout
    assert "| 1 | Phase 1: First phase  | committed |" in r.stdout
    assert "gate failed in builder (exit 1): `test -f done.txt`" in r.stdout
    assert (run_dir(repo) / "summary.md").read_text(encoding="utf-8").startswith("# Run ")


def test_summarize_takes_a_run_id_and_defaults_to_the_latest(styre, repo, commits):
    styre("run", "design.md", "--quiet")
    first = run_dir(repo).name
    styre("run", "design.md", "--quiet", "--allow-dirty")
    second = run_dir(repo).name
    assert f"# Run {second}" in styre("summarize").stdout
    assert f"# Run {first}" in styre("summarize", first).stdout
    assert f"# Run {first}" in styre("summarize", f".styre/runs/{first}").stdout


def test_summarize_without_any_run_says_so(styre, repo, commits):
    r = styre("summarize")
    assert r.returncode == 1 and "No runs found" in r.stderr
    r = styre("summarize", "20990101-000000")
    assert r.returncode == 1 and "No such run" in r.stderr


def test_a_missing_pi_config_stops_the_run_with_instructions(styre, repo, commits, tmp_path):
    """An unattended run uses styre's own pi config, never the operator's interactive one:
    measured 2026-09-23, the interactive setup put 22,439 chars of web-search tool schemas
    and writing-style rules into every request — 47% of a phase's starting context."""
    r = styre("run", "design.md", "--quiet",
              env_extra={"STYRE_PI_CONFIG_DIR": str(tmp_path / "nope")})
    assert r.returncode == 1
    assert "No pi config for styre at" in r.stderr
    assert "mkdir -p" in r.stderr and "put no AGENTS.md beside it" in r.stderr
    assert commits() == ["initial"]


def test_pi_runs_under_styres_own_config_dir(styre, repo, commits, pi_config):
    """pi gets styre's config directory, and the run records which one it used."""
    styre("run", "design.md", "--quiet")
    start = next(e for e in timeline(repo) if e["event"] == "run_start")
    assert start["pi_config"] == str(pi_config)
    # fake_pi writes the value it was given, so this is what the child actually saw.
    seen = (run_dir(repo) / "phase1.piconfig").read_text(encoding="utf-8").strip()
    assert seen == str(pi_config)


def test_pi_missing_from_path_fails_before_anything_runs(styre, repo, commits):
    r = styre("run", "design.md", path="/nonexistent")
    assert r.returncode == 1
    assert "not found on PATH" in r.stderr
    assert commits() == ["initial"]


def test_a_dirty_tree_is_refused(styre, repo, commits):
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    r = styre("run", "design.md", "--quiet")
    assert r.returncode == 1
    assert "Working tree is not clean" in r.stderr


def test_the_gate_and_the_commit_are_narrated_as_they_happen(styre, repo, commits):
    """A gate is the longest silence in a phase; an unattended run should say what it is on."""
    r = styre("run", "design.md", "--quiet",
              plan={"phase1.prompt.md": "bad_gate", "phase1.fix1.md": "ok"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "$ test -f done.txt → FAILED (exit 1)" in r.stdout      # the round that failed
    assert "$ test -f done.txt → ok (" in r.stdout                 # and the one that passed
    assert "test guard → ok" in r.stdout
    assert "✓ committed " in r.stdout and "Phase 1: First phase" in r.stdout


def test_the_agents_output_is_stamped_with_how_far_into_the_phase_it_is(styre, repo, commits):
    styre("run", "design.md")
    log = (run_dir(repo) / "logs" / "phase1.log").read_text(encoding="utf-8")
    assert "[+00:0" in log
    assert "⚙ bash" in log          # the tool call is stamped too, not just the reply


def test_the_readable_log_is_written_while_the_phase_is_still_running(styre, repo):
    """`tail -f` on the log has to follow a phase in flight, not appear once it is over."""
    # The fake agent prints its whole transcript and then sleeps, so anything in the log
    # before the idle watchdog kills it was necessarily written mid-phase.
    p = styre("run", "design.md", "--quiet", "--timeout", "3", default="hang", background=True)
    try:
        seen = ""
        for _ in range(100):
            logs = list((repo / ".styre" / "runs").glob("*/logs/phase1.log"))
            if logs:
                seen = logs[0].read_text(encoding="utf-8")
            if "Ran phase1.prompt.md" in seen:
                break
            time.sleep(0.2)
        assert "Ran phase1.prompt.md" in seen
    finally:
        assert p.wait(timeout=60) == 1          # the watchdog stopped it; no orphaned pi
        p.stdout.close()
    # The watchdog measures silence, not total runtime, and the log says which it was.
    assert "TIMEOUT: no output for 3s" in (
        run_dir(repo) / "logs" / "phase1.log").read_text(encoding="utf-8")


def test_events_and_log_are_written_separately(styre, repo, commits):
    styre("run", "design.md", "--quiet")
    events = (run_dir(repo) / "logs" / "phase1.events.jsonl").read_text(encoding="utf-8")
    first = json.loads(events.splitlines()[0])
    assert set(first) == {"ts", "line"}
    assert "thinking_delta" in events                      # the raw stream keeps everything
    log = (run_dir(repo) / "logs" / "phase1.log").read_text(encoding="utf-8")
    assert "thinking_delta" not in log                     # the readable log does not
    assert "$ test -f done.txt" in log                     # gate output lands here too


# --- context management: extensions, fix rounds, relays ------------------------------------

def with_window(pi_config, window=1000):
    """A pi config naming a default model with a context window: relay at 75%, resume below
    50% (750 and 500 tokens here)."""
    (pi_config / "settings.json").write_text(json.dumps(
        {"defaultProvider": "p", "defaultModel": "m"}), encoding="utf-8")
    (pi_config / "models.json").write_text(json.dumps({"providers": {"p": {
        "baseUrl": "http://127.0.0.1:1/v1", "models": [{"id": "m", "contextWindow": window}]}}}),
        encoding="utf-8")


def argvs(repo):
    return [json.loads(line) for line in (run_dir(repo) / "pi-argv.jsonl").read_text().splitlines()]


def attached(argv):
    return [a[1:].rsplit("/", 1)[-1] for a in argv if a.startswith("@")]


def test_every_pi_step_loads_styres_extensions(styre, repo):
    from styre.config import PI_EXTENSIONS
    styre("run", "design.md", "--quiet")
    names = {p.name for p in PI_EXTENSIONS}
    assert names == {"cap-output.js", "no-compaction.js", "strip-thinking.js"}
    for argv in argvs(repo):
        loaded = {argv[i + 1].rsplit("/", 1)[-1] for i, a in enumerate(argv) if a == "--extension"}
        assert loaded == names


def test_a_fresh_fix_round_gets_the_phase_prompt_and_the_progress_file(styre, repo):
    r = styre("run", "design.md", "--quiet",
              plan={"phase1.prompt.md": "bad_gate", "phase1.fix1.md": "ok"})
    assert r.returncode == 0, r.stdout
    fix_argv = [a for a in argvs(repo) if "phase1.fix1.md" in attached(a)][0]
    assert attached(fix_argv) == ["phase1.prompt.md", "phase1.fix1.md"]  # the task, then what failed
    assert "--session-dir" in fix_argv and "--session" not in fix_argv
    fix = (run_dir(repo) / "phase1.fix1.md").read_text()
    assert "Done: ran phase1.prompt.md" in fix  # the progress file the builder left
    assert "test -f done.txt" in fix
    assert "fresh process" in r.stdout


def test_a_small_fix_round_resumes_the_session(styre, repo, pi_config):
    with_window(pi_config)  # the fake reports 15 tokens of context: well under 500
    r = styre("run", "design.md", "--quiet",
              plan={"phase1.prompt.md": "bad_gate", "phase1.fix1.md": "ok"})
    assert r.returncode == 0, r.stdout
    builder, fix = [a for a in argvs(repo) if attached(a) and attached(a)[-1].startswith("phase1.")][:2]
    session = fix[fix.index("--session") + 1]
    assert session.endswith(".jsonl") and "--session-dir" not in fix
    assert attached(fix) == ["phase1.fix1.md"]  # the conversation already holds the phase
    assert "resuming the session at 15 tokens" in r.stdout
    ends = [e for e in timeline(repo) if e["event"] == "pi_end" and e["phase"] == 1]
    assert [e.get("resumed") for e in ends] == [None, True]


def test_a_large_fix_round_starts_fresh(styre, repo, pi_config):
    with_window(pi_config)
    r = styre("run", "design.md", "--quiet", env_extra={"FAKE_PI_CONTEXT": "550"},  # 500 ≤ 550 < 750
              plan={"phase1.prompt.md": "bad_gate", "phase1.fix1.md": "ok"})
    assert r.returncode == 0, r.stdout
    fix = [a for a in argvs(repo) if "phase1.fix1.md" in attached(a)][0]
    assert "--session" not in fix and attached(fix) == ["phase1.prompt.md", "phase1.fix1.md"]


def test_a_step_past_the_threshold_continues_in_a_fresh_process(styre, repo, pi_config, commits):
    with_window(pi_config)
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "grow"}, timeout=60)
    assert r.returncode == 0, r.stdout
    assert commits()[:2] == ["Phase 2: Second phase", "Phase 1: First phase"]
    relays = [e for e in timeline(repo) if e["event"] == "relay"]
    assert [(e["phase"], e["step"], e["context"], e["relay_at"]) for e in relays] == [
        (1, "builder", 900, 750)]
    relay_argv = [a for a in argvs(repo) if "phase1.relay1.md" in attached(a)][0]
    assert attached(relay_argv) == ["phase1.prompt.md", "phase1.relay1.md"]
    text = (run_dir(repo) / "phase1.relay1.md").read_text()
    assert "fresh process" in text and "Done: ran phase1.prompt.md" in text
    assert "Learned: handed off by phase1.handoff1.md" in text  # the handoff turn wrote it
    assert [e["rounds"] for e in timeline(repo) if e["event"] == "phase_end"][0] == 0  # not a fix round
    assert [e["relays"] for e in timeline(repo) if e["event"] == "phase_end"][0] == 1


def test_a_relay_first_resumes_the_stopped_step_to_write_its_progress(styre, repo, pi_config):
    """app phase 3, 2026-09-28: the builder was stopped at 72k without ever writing its progress
    file, so the first fresh start began blind and spent 80 minutes re-reading the tree."""
    with_window(pi_config)
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "grow"}, timeout=60)
    assert r.returncode == 0, r.stdout
    names = [attached(a) for a in argvs(repo) if attached(a)]
    assert names[:3] == [["phase1.prompt.md"], ["phase1.handoff1.md"],
                         ["phase1.prompt.md", "phase1.relay1.md"]]
    handoff = [a for a in argvs(repo) if attached(a) == ["phase1.handoff1.md"]][0]
    assert handoff[handoff.index("--session") + 1].endswith(".jsonl")  # the stopped session
    assert "--session-dir" not in handoff
    ends = [e for e in timeline(repo) if e["event"] == "pi_end" and e["phase"] == 1]
    assert [(e["step"], e.get("handoff"), e["rc"]) for e in ends][:2] == [
        ("builder", None, 75), ("builder handoff", True, 0)]
    assert "resumed" not in ends[1]  # not a resumed fix round
    # The fake handoff keeps working for 60 s after writing the file; styre ends it at the
    # first turn end once the file has changed.
    assert ends[1]["seconds"] < 30


def test_a_fresh_start_that_changes_nothing_stops_the_phase(styre, repo, pi_config, commits):
    with_window(pi_config)
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "grow"}, default="stuck",
              timeout=120)
    assert r.returncode == 1
    assert "fresh start 1 filled its context" in r.stdout and "without changing" in r.stdout
    assert [e["relays"] for e in timeline(repo) if e["event"] == "relay"] == [1, 2]
    assert commits() == ["initial"]


def test_relays_are_bounded(styre, repo, pi_config, commits):
    with_window(pi_config)
    r = styre("run", "design.md", "--quiet", default="grow", timeout=120)
    assert r.returncode == 1
    assert "fresh starts did not finish the phase" in r.stdout and "split it" in r.stdout
    assert commits() == ["initial"]


def test_a_step_that_finished_before_its_last_turn_is_not_relayed(styre, repo, pi_config, commits):
    with_window(pi_config)
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "grow_done"}, timeout=60)
    assert r.returncode == 0, r.stdout
    assert not [e for e in timeline(repo) if e["event"] == "relay"]
    assert "Phase 1: First phase" in commits()


def test_a_resume_continues_only_a_run_of_the_same_design(styre, repo):
    """--from-phase used to continue the latest run whatever design it ran; two designs' phases
    then shared one directory's event files, and each summary counted the other's tokens."""
    styre("run", "design.md", "--quiet")
    first = run_dir(repo)
    (repo / "other.md").write_text((repo / "design.md").read_text(), encoding="utf-8")
    r = styre("run", "other.md", "--quiet", "--from-phase", "2", "--allow-dirty")
    assert "the latest run" in r.stdout and "starting a new run directory" in r.stdout
    assert run_dir(repo) != first
    r = styre("run", "other.md", "--quiet", "--from-phase", "2", "--allow-dirty")
    assert "starting a new run directory" not in r.stdout  # same design: continued
