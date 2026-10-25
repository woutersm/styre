"""`evals/bench.py` against the two junit XML samples the benchmark runners write."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))

import bench  # noqa: E402

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
