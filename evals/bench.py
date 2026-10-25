"""Score a benchmark run's reference test suite, written as junit XML by the design's own runner.

    python evals/bench.py <junit.xml> --keep-glob <glob> [--expected-new N] [--expected-keep N]

This phase provides `read_junit` and `score`; a later phase adds the run runner.
"""
from __future__ import annotations

import fnmatch
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def read_junit(path):
    """Return `[(id, passed), ...]` for every `<testcase>` in the file, in order.

    `id` is `"<classname>::<name>"`; `passed` is true when the testcase has no `failure`,
    `error` or `skipped` child. A missing or unparseable file gives `[]`.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    cases = []
    for tc in root.iter("testcase"):
        passed = tc.find("failure") is None and tc.find("error") is None and tc.find("skipped") is None
        cases.append(
            (
                f"{tc.get('classname', '')}::{tc.get('name', '')}",
                passed,
            )
        )
    return cases


def score(cases, keep_glob, expected_new, expected_keep):
    """Score reference `[(id, passed), ...]` cases; see the module docstring for the dict.

    Returns `{"new": [passed, total], "keep": [passed, total], "failing": [...],
    "regressions": [...], "missing": n}`. A testcase whose `classname` matches
    `"*" + keep_glob` is a keep test; everything else is a new test. Each kind's `total`
    is the larger of its expected count and the number seen, so a test that never ran
    counts as failed. `failing` and `regressions` are the sorted ids of new and keep
    tests that did not pass; `missing` is how many expected tests (new and keep
    together) were not seen at all.
    """
    new = [c for c in cases if not fnmatch.fnmatchcase(c[0].split("::")[0], "*" + keep_glob)]
    keep = [c for c in cases if c not in new]
    result = {}
    for kind, cases_, expected in (("new", new, expected_new), ("keep", keep, expected_keep)):
        passed = sum(1 for _, ok in cases_ if ok)
        total = max(expected, len(cases_))
        result[kind] = [passed, total]
        result[kind + "_ids"] = [i for i, _ in cases_]
    result["failing"] = sorted(i for i, ok in new if not ok)
    result["regressions"] = sorted(i for i, ok in keep if not ok)
    result["missing"] = max(0, expected_new - len(new)) + max(0, expected_keep - len(keep))
    del result["new_ids"], result["keep_ids"]
    return result


def main(argv=None):
    """Score each junit XML file given on the command line; print one JSON line each."""
    args = sys.argv[1:] if argv is None else list(argv)
    keep_glob = "test_keep_*"
    expected_new = expected_keep = 0
    files = []
    i = 0
    while i < len(args):
        if args[i] == "--keep-glob":
            keep_glob = args[i + 1]
            i += 2
        elif args[i] == "--expected-new":
            expected_new = int(args[i + 1])
            i += 2
        elif args[i] == "--expected-keep":
            expected_keep = int(args[i + 1])
            i += 2
        else:
            files.append(args[i])
            i += 1
    for path in files:
        print(json.dumps(score(read_junit(path), keep_glob, expected_new, expected_keep)))


if __name__ == "__main__":
    main()
