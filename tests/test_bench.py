"""`evals/bench.py`: scoring the reference junit XML, and running one benchmark design.

The scoring tests use the two junit samples the benchmark runners write. The run tests drive
the whole thing with real styre and the fake agent (a lean git repository, a design, a
reference suite) and check the `result.json` each produces.
"""
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))

import bench  # noqa: E402
import bench_report  # noqa: E402
from conftest import DESIGN  # noqa: E402

# --- scoring the reference junit XML --------------------------------------------

PYTEST_SAMPLE = """\
<testsuites name="pytest tests"><testsuite name="pytest" tests="3">
<testcase classname="bench_reference.test_keep_a" name="test_p[blank-name]" time="0.000" />
<testcase classname="bench_reference.test_keep_a" name="test_err" time="0.000">
<failure message="RuntimeError: boom">...</failure></testcase>
<testcase classname="bench_reference.test_ref_a" name="test_ok" time="0.000" />
</testsuite></testsuites>
"""

VITEST_SAMPLE = """\
<testsuites name="vitest tests" tests="3">
<testsuite name="test/bench_ref/x.ref.test.ts" tests="2">
<testcase classname="test/bench_ref/x.ref.test.ts" name="group &gt; passes" time="0.0007"></testcase>
<testcase classname="test/bench_ref/x.ref.test.ts" name="group &gt; fails" time="0.0029">
<failure message="expected 1 to be 2" type="AssertionError">...</failure></testcase>
</testsuite>
<testsuite name="test/bench_ref/x.keep.test.ts" tests="1">
<testcase classname="test/bench_ref/x.keep.test.ts" name="kept" time="0.0007"></testcase>
</testsuite></testsuites>
"""


def pytest_sample(tmp_path):
    path = tmp_path / "pytest.xml"
    path.write_text(PYTEST_SAMPLE, encoding="utf-8")
    return path


def vitest_sample(tmp_path):
    path = tmp_path / "vitest.xml"
    path.write_text(VITEST_SAMPLE, encoding="utf-8")
    return path


def test_missing_file_reads_empty():
    assert bench.read_junit("/nonexistent/such/a/file.xml") == []


def test_unparseable_file_reads_empty(tmp_path):
    path = tmp_path / "not-xml.xml"
    path.write_text("this is not < xml at all", encoding="utf-8")
    assert bench.read_junit(path) == []


def test_pytest_sample(tmp_path):
    cases = bench.read_junit(pytest_sample(tmp_path))
    assert [i for i, _ in cases] == [
        "bench_reference.test_keep_a::test_p[blank-name]",
        "bench_reference.test_keep_a::test_err",
        "bench_reference.test_ref_a::test_ok",
    ]
    assert [ok for _, ok in cases] == [True, False, True]
    result = bench.score(cases, "test_keep_*", 0, 0)
    assert result["new"] == [1, 1]
    assert result["keep"] == [1, 2]
    assert result["failing"] == []
    assert result["regressions"] == ["bench_reference.test_keep_a::test_err"]
    assert result["missing"] == 0


def test_vitest_sample(tmp_path):
    cases = bench.read_junit(vitest_sample(tmp_path))
    assert [i for i, _ in cases] == [
        "test/bench_ref/x.ref.test.ts::group > passes",
        "test/bench_ref/x.ref.test.ts::group > fails",
        "test/bench_ref/x.keep.test.ts::kept",
    ]
    result = bench.score(cases, "*.keep.test.*", 0, 0)
    assert result["new"] == [1, 2]
    assert result["keep"] == [1, 1]
    assert result["failing"] == ["test/bench_ref/x.ref.test.ts::group > fails"]
    assert result["regressions"] == []
    assert result["missing"] == 0


def test_expected_new_counts_missing(tmp_path):
    cases = bench.read_junit(vitest_sample(tmp_path))
    result = bench.score(cases, "*.keep.test.*", 5, 0)
    assert result["new"] == [1, 5]
    assert result["keep"] == [1, 1]
    assert result["missing"] == 3


# --- running one benchmark design ----------------------------------------------


def make_design_dir(tmp_path, repo, start=None):
    """A design directory: bench.json, the brief design, and the reference suite."""
    start = start or subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                    check=True, text=True, capture_output=True).stdout.strip()
    design_dir = tmp_path / "design"
    (design_dir / "reference").mkdir(parents=True)
    # The gates fail while a reference suite is present, so the run cannot be scored against
    # a suite copied in mid-run: the agent has to finish the real work first.
    brief = DESIGN.replace("test -f done.txt", "test ! -e bench_reference && test -f done.txt")
    (design_dir / "brief.md").write_text(brief, encoding="utf-8")
    (design_dir / "reference" / "test_ref_done.py").write_text(
        "from pathlib import Path\n\n"
        "def test_ref():\n    assert Path('done.txt').exists()\n", encoding="utf-8")
    (design_dir / "reference" / "test_keep_readme.py").write_text(
        "from pathlib import Path\n\n"
        "def test_keep():\n    assert Path('README.md').exists()\n", encoding="utf-8")
    bench_json = {
        "repo": str(repo),
        "start": start,
        "design_path": "design.md",
        "phases": 2,
        "setup": ["true"],
        "reference": {
            "keep": "test_keep_*",
            "parts": [{
                "dir": "reference",
                "into": "bench_reference",
                "command": (f"{sys.executable} -m pytest -q -p no:cacheprovider "
                            f"bench_reference --junitxml={{junit}}"),
            }],
        },
        "checked": {"start": {"commit": start[:7], "new": [0, 1], "keep": [1, 1]}},
        "designs": {"brief": "brief.md"},
    }
    (design_dir / "bench.json").write_text(json.dumps(bench_json, indent=2), encoding="utf-8")
    return design_dir


SETUP = {"name": "omlx072-dflash2-4bit", "hardware": "M4 Pro 48 GB",
         "server": {"name": "oMLX", "version": "0.7.2"},
         "speculative": {"method": "DFlash 2", "draft": "Splash DFlash 2 draft"}}


def make_pi_config(tmp_path):
    """A pi config naming provider `local` / model `m`, as the design asks for."""
    d = tmp_path / "piconfig"
    d.mkdir()
    (d / "settings.json").write_text(
        json.dumps({"defaultProvider": "local", "defaultModel": "m"}), encoding="utf-8")
    (d / "models.json").write_text(
        json.dumps({"providers": {"local": {
            "baseUrl": "http://localhost:1/v1",
            "models": [{"id": "m", "contextWindow": 1000}]}}}), encoding="utf-8")
    return d


def patch_env(monkeypatch, fake_pi, pi_config, default):
    monkeypatch.setenv("PATH", fake_pi)
    monkeypatch.setenv("STYRE_PI_CONFIG_DIR", str(pi_config))
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FAKE_PI_DEFAULT", default)
    # CI has no git identity: the clone's re-init would otherwise not be able to commit.
    for var, value in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.com"),
                       ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.com")):
        monkeypatch.setenv(var, value)


def make_styre_config(tmp_path):
    """A styre.json with a short frontier deadline, for bench --plan tests."""
    cfg = tmp_path / "styre.json"
    cfg.write_text('{"frontier": {"command": ["claude"], "timeout": 60}}', encoding="utf-8")
    return cfg


def git_log(repo):
    out = subprocess.run(["git", "log", "--format=%s"], cwd=repo,
                         capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def test_bench_ok(monkeypatch, tmp_path, repo, fake_pi):
    pi_config = make_pi_config(tmp_path)
    (pi_config / "setup.json").write_text(json.dumps(SETUP), encoding="utf-8")
    patch_env(monkeypatch, fake_pi, pi_config, "ok")
    design_dir = make_design_dir(tmp_path, repo)
    design = json.loads((design_dir / "bench.json").read_text(encoding="utf-8"))
    design["repo"] = str(repo)
    (design_dir / "bench.json").write_text(json.dumps(design), encoding="utf-8")
    out = bench.run_bench(design_dir, "brief", f"{sys.executable} -m styre",
                          tmp_path / "results", pi_config=str(pi_config), label="bench-test")
    result = json.loads(Path(out["_dir"]).read_text(encoding="utf-8"))
    assert result["error"] is None
    assert result["planned"] is False  # run without --plan: no plan, no frontier
    assert result["plan_hours"] is None and result["frontier"] is None
    assert result["new"] == [1, 1]
    assert result["keep"] == [1, 1]
    assert result["committed"] == 2
    assert result["exit_code"] == 0
    assert result["run_id"]
    assert result["usage"]["requests"] > 0
    assert result["model"] == {"provider": "local", "id": "m",
                               "base_url": "http://localhost:1/v1",
                               "context_window": 1000, "thinking": None}
    assert result["label"] == "bench-test"
    assert result["setup"] == SETUP


def test_bench_blocked(monkeypatch, tmp_path, repo, fake_pi):
    pi_config = make_pi_config(tmp_path)
    patch_env(monkeypatch, fake_pi, pi_config, "blocked")
    design_dir = make_design_dir(tmp_path, repo)
    design = json.loads((design_dir / "bench.json").read_text(encoding="utf-8"))
    design["repo"] = str(repo)
    (design_dir / "bench.json").write_text(json.dumps(design), encoding="utf-8")
    out = bench.run_bench(design_dir, "brief", f"{sys.executable} -m styre",
                          tmp_path / "results", pi_config=str(pi_config))
    result = json.loads(Path(out["_dir"]).read_text(encoding="utf-8"))
    assert result["new"] == [0, 1]
    assert result["committed"] == 0
    assert result["exit_code"] is not None and result["exit_code"] != 0
    assert result["stopped"]
    assert result["keep"] == [1, 1]  # the keep test still passes on the reset tree


def test_bench_copy_has_no_source_history(monkeypatch, tmp_path, repo, fake_pi):
    pi_config = make_pi_config(tmp_path)
    patch_env(monkeypatch, fake_pi, pi_config, "ok")
    design_dir = make_design_dir(tmp_path, repo)
    design = json.loads((design_dir / "bench.json").read_text(encoding="utf-8"))
    design["repo"] = str(repo)
    (design_dir / "bench.json").write_text(json.dumps(design), encoding="utf-8")
    out = bench.run_bench(design_dir, "brief", f"{sys.executable} -m styre",
                          tmp_path / "results")
    result_dir = Path(out["_dir"]).parent
    assert not (result_dir / "repo").exists()
    assert (result_dir / ".styre" / "latest.txt").is_file()
    copy = tmp_path / "unbundled"
    subprocess.run(["git", "clone", "--quiet", str(result_dir / "repo.bundle"), str(copy)],
                   check=True)
    log = git_log(copy)
    assert "initial" not in log
    assert any("bench: brief design" in s for s in log)
    assert sum(1 for s in log if s.startswith("Phase")) == 2
    assert sum(1 for s in log if s.startswith("bench: start")) == 1


def test_clone_source_keeps_urls_and_expands_paths():
    assert bench.clone_source("https://github.com/o/r") == "https://github.com/o/r"
    assert bench.clone_source("file:///tmp/r") == "file:///tmp/r"
    assert bench.clone_source("git@github.com:o/r.git") == "git@github.com:o/r.git"
    assert bench.clone_source("~/Dev/r") == str(Path.home() / "Dev" / "r")
    assert bench.clone_source("/abs/r") == str(Path("/abs/r"))


def test_bench_clones_from_a_url(monkeypatch, tmp_path, repo, fake_pi):
    pi_config = make_pi_config(tmp_path)
    patch_env(monkeypatch, fake_pi, pi_config, "ok")
    design_dir = make_design_dir(tmp_path, repo)
    design = json.loads((design_dir / "bench.json").read_text(encoding="utf-8"))
    design["repo"] = Path(repo).resolve().as_uri()
    (design_dir / "bench.json").write_text(json.dumps(design), encoding="utf-8")
    out = bench.run_bench(design_dir, "brief", f"{sys.executable} -m styre",
                          tmp_path / "results")
    assert out["new"] == [1, 1]


def test_bench_setup_failure(monkeypatch, tmp_path, repo, fake_pi):
    pi_config = make_pi_config(tmp_path)
    patch_env(monkeypatch, fake_pi, pi_config, "ok")
    design_dir = make_design_dir(tmp_path, repo)
    design = json.loads((design_dir / "bench.json").read_text(encoding="utf-8"))
    design["repo"] = str(repo)
    design["setup"] = ["false"]
    (design_dir / "bench.json").write_text(json.dumps(design), encoding="utf-8")
    out = bench.run_bench(design_dir, "brief", f"{sys.executable} -m styre",
                          tmp_path / "results")
    result = json.loads(Path(out["_dir"]).read_text(encoding="utf-8"))
    assert "false" in result["error"]
    assert result["exit_code"] is None
    assert result["run_id"] is None
    assert result["committed"] is None
    assert result["new"] is None


# --- `--plan`: the frontier plans the design before the run ----------------------


def planned_design():
    """The conftest brief (gates as in make_design_dir) with one implementation-help line
    added, keeping every line and gate the brief has."""
    brief = DESIGN.replace("test -f done.txt", "test ! -e bench_reference && test -f done.txt")
    return brief.replace("Preamble every phase needs.",
                         "Preamble every phase needs.\nThe tests run with `uv run pytest -q`.")


def claude_reply_json(planned, ok=True):
    return json.dumps({
        "type": "result", "subtype": "success" if ok else "error_max_turns",
        "is_error": not ok, "num_turns": 1, "structured_output": {"design": planned} if ok else None,
        "total_cost_usd": 0.161, "duration_ms": 6125,
        "usage": {"input_tokens": 4, "cache_creation_input_tokens": 19268,
                  "cache_read_input_tokens": 5017, "output_tokens": 301,
                  "output_tokens_details": {"thinking_tokens": 63}},
        "modelUsage": {"claude-opus-5-5": {"inputTokens": 4, "outputTokens": 301,
                                          "costUSD": 0.161}},
    } if ok else {
        "type": "result", "subtype": "error_max_budget_usd", "is_error": True, "num_turns": 2,
        "structured_output": None, "total_cost_usd": 0.0001, "duration_ms": 2511,
        "usage": {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                  "output_tokens": 0, "output_tokens_details": {"thinking_tokens": 0}},
        "errors": ["Reached maximum budget ($0.0001)"],
    })


def bench_env(monkeypatch, tmp_path, fake_pi, fake_claude, pi_config, default, reply):
    patch_env(monkeypatch, fake_pi, pi_config, default)
    monkeypatch.setenv("STYRE_CONFIG", str(make_styre_config(tmp_path)))
    log = tmp_path / "fake_claude.log"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_REPLY", str(reply))
    monkeypatch.delenv("FAKE_CLAUDE_EXIT", raising=False)
    return log


def test_bench_plan_plans_then_runs(monkeypatch, tmp_path, repo, fake_pi, fake_claude):
    pi_config = make_pi_config(tmp_path)
    reply = tmp_path / "planned.json"
    reply.write_text(claude_reply_json(planned_design()), encoding="utf-8")
    bench_env(monkeypatch, tmp_path, fake_pi, fake_claude, pi_config, "ok", reply)
    design_dir = make_design_dir(tmp_path, repo)
    design = json.loads((design_dir / "bench.json").read_text(encoding="utf-8"))
    design["repo"] = str(repo)
    (design_dir / "bench.json").write_text(json.dumps(design), encoding="utf-8")
    out = bench.run_bench(design_dir, "brief", f"{sys.executable} -m styre",
                          tmp_path / "results", pi_config=str(pi_config), plan=True)
    result_dir = Path(out["_dir"]).parent
    result = json.loads(Path(out["_dir"]).read_text(encoding="utf-8"))
    assert result["error"] is None, result["error"]
    assert result["planned"] is True
    assert result["plan_hours"] is not None
    assert result["frontier"] == {"calls": 1, "tokens_in": 24289, "tokens_out": 301,
                                  "cost_usd": 0.161}
    assert result["committed"] == 2  # the run ran the design and committed every phase
    assert (result_dir / "plan.log").exists()
    assert "tokens in" in (result_dir / "plan.log").read_text(encoding="utf-8")  # the planner's usage
    root = result_dir / ".styre" / "runs"  # a result keeps .styre/ beside repo.bundle
    timeline = (root / result["run_id"] / "timeline.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in timeline.splitlines()]
    start = [e for e in events if e["event"] == "run_start"][0]
    # the run ran the planned design, not the brief: its hash is the planned text's hash.
    assert start["design_sha256"] == hashlib.sha256(
        planned_design().encode("utf-8")).hexdigest()[:16]


def test_bench_plan_failure_records_the_error_and_skips_the_run(monkeypatch, tmp_path, repo,
                                                                fake_pi, fake_claude):
    pi_config = make_pi_config(tmp_path)
    reply = tmp_path / "fail.json"
    reply.write_text(claude_reply_json(None, ok=False), encoding="utf-8")
    bench_env(monkeypatch, tmp_path, fake_pi, fake_claude, pi_config, "ok", reply)
    design_dir = make_design_dir(tmp_path, repo)
    design = json.loads((design_dir / "bench.json").read_text(encoding="utf-8"))
    design["repo"] = str(repo)
    (design_dir / "bench.json").write_text(json.dumps(design), encoding="utf-8")
    out = bench.run_bench(design_dir, "brief", f"{sys.executable} -m styre",
                          tmp_path / "results", pi_config=str(pi_config), plan=True)
    result_dir = Path(out["_dir"]).parent
    result = json.loads(Path(out["_dir"]).read_text(encoding="utf-8"))
    assert result["planned"] is False
    assert result["error"] == "styre plan failed: " + (
        result_dir / "plan.log").read_text(encoding="utf-8") \
        .strip().splitlines()[-1]
    assert result["error"].startswith("styre plan failed: ")
    assert "Reached maximum budget" in result["error"]
    assert result["run_id"] is None and result["hours"] is None  # the design was not run
    assert result["new"] is None
    assert (result_dir / "plan.log").exists()
    assert not (result_dir / "styre.log").exists()  # the run was skipped, not killed


def limit_stream(five_hour, seven_day, five_resets=1793491200, seven_resets=1793746800):
    """What `claude -p --output-format stream-json --verbose` prints on a subscription: a
    `rate_limit_event` among the other lines (shape captured 2026-10-31)."""
    event = {"type": "rate_limit_event", "rate_limit_info": {
        "status": "allowed", "rateLimitType": "five_hour", "unifiedWindows": {
            "five_hour": {"utilization": five_hour, "resetsAt": five_resets, "status": "allowed"},
            "seven_day": {"utilization": seven_day, "resetsAt": seven_resets,
                          "status": "allowed"}}}}
    return "\n".join([json.dumps({"type": "system", "subtype": "init"}), json.dumps(event),
                      json.dumps({"type": "result", "subtype": "success", "is_error": False})])


def plan_with_limits(monkeypatch, tmp_path, repo, fake_pi, fake_claude, after):
    """A planned bench run whose fake claude answers: 1 the limits before, 2 the plan,
    3 the limits after (`after` is the stream to print)."""
    pi_config = make_pi_config(tmp_path)
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "1.json").write_text(limit_stream(0.23, 0.53), encoding="utf-8")
    (replies / "2.json").write_text(claude_reply_json(planned_design()), encoding="utf-8")
    (replies / "3.json").write_text(after, encoding="utf-8")
    log = bench_env(monkeypatch, tmp_path, fake_pi, fake_claude, pi_config, "ok", replies)
    design_dir = make_design_dir(tmp_path, repo)
    design = json.loads((design_dir / "bench.json").read_text(encoding="utf-8"))
    design["repo"] = str(repo)
    (design_dir / "bench.json").write_text(json.dumps(design), encoding="utf-8")
    out = bench.run_bench(design_dir, "brief", f"{sys.executable} -m styre",
                          tmp_path / "results", pi_config=str(pi_config), plan=True)
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return json.loads(Path(out["_dir"]).read_text(encoding="utf-8")), calls


def test_bench_plan_records_the_subscription_limits_it_used(monkeypatch, tmp_path, repo,
                                                           fake_pi, fake_claude):
    result, calls = plan_with_limits(monkeypatch, tmp_path, repo, fake_pi, fake_claude,
                                     limit_stream(0.51, 0.57))
    assert result["error"] is None, result["error"]
    assert result["limits"] == {
        "five_hour": {"before": 0.23, "after": 0.51, "used": 0.28},
        "seven_day": {"before": 0.53, "after": 0.57, "used": 0.04}}
    assert len(calls) == 3  # the probe, the plan, the probe
    assert "stream-json" in calls[0]["argv"] and "haiku" in calls[0]["argv"]
    assert "stream-json" in calls[2]["argv"]


def test_a_window_that_resets_during_the_plan_has_no_used_value(monkeypatch, tmp_path, repo,
                                                               fake_pi, fake_claude):
    result, _ = plan_with_limits(monkeypatch, tmp_path, repo, fake_pi, fake_claude,
                                 limit_stream(0.05, 0.57, five_resets=1793509200))
    assert result["limits"]["five_hour"] == {"before": 0.23, "after": 0.05, "used": None}
    assert result["limits"]["seven_day"]["used"] == 0.04


def test_bench_plan_without_limit_events_records_none(monkeypatch, tmp_path, repo, fake_pi,
                                                      fake_claude):
    """An API-key account prints no rate_limit_event; the plan's numbers stand alone."""
    result, _ = plan_with_limits(monkeypatch, tmp_path, repo, fake_pi, fake_claude,
                                 json.dumps({"type": "result", "subtype": "success"}))
    assert result["error"] is None, result["error"]
    assert result["limits"] is None


# --- the benchmark report ---------------------------------------------------------

MODEL = {"provider": "splash", "id": "mlx-community/Qwen3.8-27B-4bit",
         "base_url": None, "context_window": 120000, "thinking": None}


def mk_result(tmp_path, name, **over):
    """Write one small `result.json` under `tmp_path` and return its path."""
    r = {"design": "splash", "variant": "brief", "styre": "0.25.0", "label": "splash 0.4",
         "model": dict(MODEL), "served": None, "start": None,
         "started": "2026-10-25T10:00:00+00:00", "hours": 1.1, "exit_code": 0,
         "run_id": "r1", "phases": 17, "committed": 15, "stopped": None, "error": None,
         "new": [15, 17], "keep": [9, 9], "failing": 0, "regressions": [], "missing": 0,
         "parts": None, "usage": {"requests": 40, "input": 5378, "cache_read": 6784,
                                  "output": 229, "peak": 0, "prefill_seconds": 60,
                                  "decode_seconds": 3600, "agent_seconds": 0, "gate_seconds": 0}}
    r.update(over)
    r.setdefault("planned", False)
    r.setdefault("plan_hours", None)
    r.setdefault("frontier", None)
    path = tmp_path / name / "result.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(r, indent=2), encoding="utf-8")
    return path


def report(tmp_path, *paths):
    return bench_report.render([str(p) for p in paths])


def test_report_one_config_two_results(tmp_path):
    a = mk_result(tmp_path, "a", new=[15, 17], hours=1.10)
    b = mk_result(tmp_path, "b", new=[17, 17], hours=1.32,
                  started="2026-10-25T11:00:00+00:00")
    text = report(tmp_path, a, b)
    assert len(re.findall(r"\| Design +\| Started", text)) == 1  # one table per configuration
    assert re.search(r"\| Design +\| Started +\| New +\| Keep +\| Phases +\| Hours +\|", text)
    assert re.search(r"\| 15/17 \(88%\) +\|", text)  # the New cell
    assert re.search(r"\| 17/17 \(100%\) +\|", text)
    assert re.search(r"\| 15/17 +\|", text)  # the Phases cell
    assert re.search(r"\| 18/18 +\|", text)  # the Keep cell of the total row
    assert "## Configurations" not in text  # one configuration: no comparison table
    assert "Spread:" in text
    assert "- splash: new 15, 17 of 17; hours 1.10, 1.32" in text
    assert "Plan h" not in text  # no planned results in this group: no frontier columns


def test_report_planned_group_gets_plan_and_frontier_columns(tmp_path):
    a = mk_result(tmp_path, "a", planned=False)
    b = mk_result(tmp_path, "b", planned=True, plan_hours=0.12,
                  frontier={"calls": 1, "tokens_in": 1000, "tokens_out": 250, "cost_usd": 0.16},
                  started="2026-10-25T11:00:00+00:00")
    text = report(tmp_path, a, b)
    assert len(re.findall(r"\| Design +\| Started", text)) == 2  # two configurations
    unplanned = text.split("## ")[1].split("## ")[0]  # the group without planned results
    planned = text.split("## styre 0.25.0, brief, planned")[1]
    assert "Plan h" not in unplanned and "Frontier tok" not in unplanned
    assert "## styre 0.25.0, brief, planned" in text  # the variant, then "planned"
    assert re.search(r"\| Plan h +\| Frontier tok +\|", planned)
    assert re.search(r"\| 0\.12 +\| 1,250 +\|", planned)  # 0.12 h, 1000 + 250 tokens
    assert re.search(r"Total.*\| 0\.12 +\| 1,250 +\|", planned)  # the total row


def test_report_planned_group_shows_the_subscription_limits_used(tmp_path):
    frontier = {"calls": 1, "tokens_in": 1000, "tokens_out": 10, "cost_usd": 1.0}
    a = mk_result(tmp_path, "a", planned=True, plan_hours=0.2, frontier=frontier,
                  limits={"five_hour": {"before": 0.23, "after": 0.51, "used": 0.28},
                          "seven_day": {"before": 0.53, "after": 0.57, "used": 0.04}})
    b = mk_result(tmp_path, "b", planned=True, plan_hours=0.1, frontier=frontier,
                  limits={"five_hour": {"before": 0.9, "after": 0.05, "used": None},
                          "seven_day": {"before": 0.57, "after": 0.6, "used": 0.03}})
    rows = [[c.strip() for c in line.strip("|").split("|")]
            for line in report(tmp_path, a, b).splitlines() if line.startswith("|")]
    assert rows[0][-2:] == ["5h used", "7d used"]
    assert [r[-2:] for r in rows[2:]] == [["28%", "4%"], ["reset", "3%"],
                                          ["28%", "7%"]]  # the total adds the values it has


def test_result_without_plan_keys_reads_as_unplanned():
    assert bench_report.config_key({"styre": "1", "variant": "brief"}) == (
        "1", "brief", None, None, None, None, None, None, None)
    assert bench_report.config_key({"styre": "1", "variant": "brief", "planned": True}) == (
        "1", "brief", True, None, None, None, None, None, None)


def test_report_heading_shows_planned_after_the_variant(tmp_path):
    a = mk_result(tmp_path, "a", planned=True, plan_hours=0.1,
                  frontier={"calls": 1, "tokens_in": 100, "tokens_out": 25,
                            "cost_usd": 0.01})
    text = report(tmp_path, a)
    assert "## styre 0.25.0, brief, planned, splash/" in text


def test_report_two_configurations(tmp_path):
    a = mk_result(tmp_path, "a")
    b = mk_result(tmp_path, "b", styre="0.26.0")
    text = report(tmp_path, a, b)
    assert len(re.findall(r"\| Design +\| Started", text)) == 2
    assert text.count("## Configurations") == 1
    assert text.count("served:") == 0
    assert re.search(r"\| styre 0\.25\.0, brief", text)
    assert re.search(r"\| styre 0\.26\.0, brief", text)


def test_report_two_configurations_by_model(tmp_path):
    a = mk_result(tmp_path, "a")
    b = mk_result(tmp_path, "b", model=dict(MODEL, id="mlx-community/Other-9B"))
    text = report(tmp_path, a, b)
    assert len(re.findall(r"\| Design +\| Started", text)) == 2
    assert text.count("## Configurations") == 1


def test_report_two_configurations_by_context_window(tmp_path):
    a = mk_result(tmp_path, "a")
    b = mk_result(tmp_path, "b", model=dict(MODEL, context_window=100000))
    text = report(tmp_path, a, b)
    assert len(re.findall(r"\| Design +\| Started", text)) == 2
    assert text.count("## Configurations") == 1
    assert "120,000 ctx" in text and "100,000 ctx" in text


def test_report_heading_leaves_out_nulls(tmp_path):
    a = mk_result(tmp_path, "a", styre=None, label=None)
    text = report(tmp_path, a)
    assert "## brief, splash/mlx-community/Qwen3.8-27B-4bit, 120,000 ctx" in text
    assert "## brief, splash/" not in text.replace("## brief, splash/mlx", "")


def test_report_heading_full_name(tmp_path):
    a = mk_result(tmp_path, "a")
    assert ("## styre 0.25.0, brief, splash/mlx-community/Qwen3.8-27B-4bit, "
            "120,000 ctx, splash 0.4") in report(tmp_path, a)


def test_report_served_line(tmp_path):
    a = mk_result(tmp_path, "a", served="local/other")
    text = report(tmp_path, a)
    assert "served: local/other" in text
    a2 = mk_result(tmp_path, "b", served="splash/mlx-community/Qwen3.8-27B-4bit")
    assert "served:" not in report(tmp_path, a2)  # same as provider/id: no line


def test_report_error_result(tmp_path):
    a = mk_result(tmp_path, "a", error="Gate failed: timeout", hours=None, stopped=None)
    text = report(tmp_path, a)
    assert "Gate failed: timeout" in text  # shown in place of the numbers it never reached
    assert re.search(r"\| Design +\|", text)
    assert "0/1" not in text  # nothing fabricated
    # a failed result does not break the totals of an otherwise fine table
    b = mk_result(tmp_path, "b")
    text = report(tmp_path, a, b)
    assert "Gate failed: timeout" in text
    assert re.search(r"\| 15/17 \(88%\) +\|", text)  # the good result's row is intact
    assert "Stops:" in text and "Gate failed: timeout" in text.split("Stops:")[1]


def test_report_stopped_result(tmp_path):
    a = mk_result(tmp_path, "a", stopped="Phase 3: blocked: cannot converge")
    text = report(tmp_path, a)
    assert "Stops:" in text
    assert "Phase 3: blocked: cannot converge" in text


def test_report_directory_reads_one_level(tmp_path):
    mk_result(tmp_path, "a", new=[15, 17], hours=1.10)
    mk_result(tmp_path, "b", new=[17, 17], hours=1.32)
    deep = tmp_path / "a" / "repo" / "deep"
    deep.mkdir(parents=True)
    (deep / "result.json").write_text(json.dumps({"design": "deep"}), encoding="utf-8")
    text = report(tmp_path, tmp_path)
    assert re.search(r"\| Design +\|", text)
    assert "15/17 (88%)" in text and "17/17 (100%)" in text
    assert "deep" not in text  # never searched below the one level


def test_report_missing_path_fails(tmp_path):
    assert bench_report.main([str(tmp_path / "nope")]) == 1


def test_a_reference_part_that_times_out_still_leaves_a_score(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    design_dir = tmp_path / "design"
    for name in ("slow", "fine"):
        (design_dir / name).mkdir(parents=True)
    (design_dir / "fine" / "test_ref_fine.py").write_text("def test_ok():\n    pass\n",
                                                         encoding="utf-8")
    design = {"reference": {"parts": [
        {"dir": "slow", "into": "slow", "command": f"{sys.executable} -c \"import time; time.sleep(5)\""},
        {"dir": "fine", "into": "fine",
         "command": f"{sys.executable} -m pytest -q -p no:cacheprovider fine --junitxml={{junit}}"},
    ]}, "checked": {"start": {"new": [0, 1], "keep": [0, 0]}}}
    monkeypatch.setattr(bench, "REF_TIMEOUT", 1)
    junit = tmp_path / "junit"
    junit.mkdir()
    sc, parts = bench.do_reference(design, design_dir, repo, junit)
    assert [p["rc"] for p in parts] == [124, 0]
    assert sc["new"] == [1, 1]


def test_report_mixes_null_and_set_fields_across_configurations(tmp_path):
    a = mk_result(tmp_path, "a", label=None)
    b = mk_result(tmp_path, "b", label="omlx 0.7.2")
    c = mk_result(tmp_path, "c", styre=None, variant=None, label=None, model={})
    text = report(tmp_path, a, b, c)
    assert len(re.findall(r"\| Design +\| Started", text)) == 3  # no group dropped
    assert "## unknown configuration" in text
    assert text.count("## Configurations") == 1


def test_report_shows_tok_per_second(tmp_path):
    # mk_result: 5,378 uncached over 60 s of prefill, 229 output over 3,600 s of decode.
    text = report(tmp_path, mk_result(tmp_path, "a"))
    assert re.search(r"\| Prefill tok/s +\| Decode tok/s +\|", text)
    assert re.search(r"\| 89\.6 +\| 0\.1 +\|", text)


def test_read_setup_is_none_without_a_file_and_on_bad_json(tmp_path):
    assert bench.read_setup(tmp_path) is None
    (tmp_path / "setup.json").write_text("{not json", encoding="utf-8")
    assert bench.read_setup(tmp_path) is None


def test_report_groups_by_setup_name(tmp_path):
    a = mk_result(tmp_path, "a", setup={"name": "splash-4bit"})
    b = mk_result(tmp_path, "b", setup={"name": "omlx072-dflash2-4bit"})
    text = report(tmp_path, a, b)
    assert len(re.findall(r"\| Design +\| Started", text)) == 2
    assert "## styre 0.25.0, brief, splash-4bit, splash/" in text
    assert "## styre 0.25.0, brief, omlx072-dflash2-4bit, splash/" in text


def test_the_cap_kills_styre_and_the_sessions_it_started(tmp_path):
    """A stand-in for styre that starts a child in a session of its own, as styre starts pi,
    and never ends: the cap stops both."""
    import os
    pidfile = tmp_path / "child.pid"
    fake = tmp_path / "fake_styre.py"
    fake.write_text(
        "import subprocess, sys, time\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'],\n"
        "                     start_new_session=True)\n"
        f"open({str(pidfile)!r}, 'w').write(str(c.pid))\n"
        "time.sleep(600)\n", encoding="utf-8")
    rc, hours, capped = bench.do_run({"design_path": "d.md"}, tmp_path,
                                     f"{sys.executable} {fake}", tmp_path, tmp_path / "s.log",
                                     cap_hours=3 / 3600)
    assert (rc, capped) == (None, True)
    assert hours < 0.01
    child = int(pidfile.read_text())
    time.sleep(0.2)
    try:
        os.kill(child, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    if alive:  # a zombie is gone in all but name: check its state
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(child)],
                               capture_output=True, text=True).stdout.strip()
        alive = bool(state) and not state.startswith("Z")
    assert not alive
    assert "[bench] stopped at the" in (tmp_path / "s.log").read_text()


def test_a_run_inside_the_cap_is_not_capped(tmp_path):
    rc, _, capped = bench.do_run({"design_path": "d.md"}, tmp_path,
                                 f"{sys.executable} -c pass", tmp_path, tmp_path / "s.log")
    assert (rc, capped) == (0, False)


def test_bench_plan_at_the_cap_records_it_and_skips_the_run(monkeypatch, tmp_path, repo,
                                                           fake_pi, fake_claude):
    pi_config = make_pi_config(tmp_path)
    reply = tmp_path / "planned.json"
    reply.write_text(claude_reply_json(planned_design()), encoding="utf-8")
    bench_env(monkeypatch, tmp_path, fake_pi, fake_claude, pi_config, "ok", reply)
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "30")
    design_dir = make_design_dir(tmp_path, repo)
    design = json.loads((design_dir / "bench.json").read_text(encoding="utf-8"))
    design["repo"] = str(repo)
    (design_dir / "bench.json").write_text(json.dumps(design), encoding="utf-8")
    out = bench.run_bench(design_dir, "brief", f"{sys.executable} -m styre",
                          tmp_path / "results", pi_config=str(pi_config), plan=True,
                          cap_hours=2 / 3600)
    result = json.loads(Path(out["_dir"]).read_text(encoding="utf-8"))
    assert result["planned"] is False
    assert result["error"] == "styre plan stopped at the 0.000555556 h cap"
    assert result["run_id"] is None and result["hours"] is None  # the brief was not run

