"""`evals/bench.py`: scoring the reference junit XML, and running one benchmark design.

The scoring tests use the two junit samples the benchmark runners write. The run tests drive
the whole thing with real styre and the fake agent (a lean git repository, a design, a
reference suite) and check the `result.json` each produces.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))

import bench  # noqa: E402
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
