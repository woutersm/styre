"""`evals/bench.py`: scoring the reference junit XML, and running one benchmark design.

The scoring tests use the two junit samples the benchmark runners write. The run tests drive
the whole thing with real styre and the fake agent (a lean git repository, a design, a
reference suite) and check the `result.json` each produces.
"""
import json
import re
import subprocess
import sys
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


def git_log(repo):
    out = subprocess.run(["git", "log", "--format=%s"], cwd=repo,
                         capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def test_bench_ok(monkeypatch, tmp_path, repo, fake_pi):
    pi_config = make_pi_config(tmp_path)
    patch_env(monkeypatch, fake_pi, pi_config, "ok")
    design_dir = make_design_dir(tmp_path, repo)
    design = json.loads((design_dir / "bench.json").read_text(encoding="utf-8"))
    design["repo"] = str(repo)
    (design_dir / "bench.json").write_text(json.dumps(design), encoding="utf-8")
    out = bench.run_bench(design_dir, "brief", f"{sys.executable} -m styre",
                          tmp_path / "results", pi_config=str(pi_config), label="bench-test")
    result = json.loads(Path(out["_dir"]).read_text(encoding="utf-8"))
    assert result["error"] is None
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
    copy = Path(out["_dir"]).parent / "repo"
    log = git_log(copy)
    assert "initial" not in log
    assert any("bench: brief design" in s for s in log)
    assert sum(1 for s in log if s.startswith("Phase")) == 2
    assert sum(1 for s in log if s.startswith("bench: start")) == 1


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
    assert "Stops:" not in text
    # total row: sums with the overall percentage, cache hit over the summed tokens
    assert re.search(r"\| 32/34 \(94%\) +\|", text)
    assert re.search(r"\| 10,756 +\|", text) and re.search(r"\| 13,568 +\|", text)
    assert re.search(r"\| 55.8% +\|", text)  # 13568/(10756+13568), over the summed tokens
    assert re.search(r"\| 2\.0 +\|", text)  # 2 * 3600 seconds of decode


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
