"""Turn `bench.py`'s result files into one markdown report.

    python evals/bench_report.py PATH...

A `PATH` is a `result.json`, or a directory: its own `result.json` when it has one, else each
`*/result.json` one level down. Never deeper: result directories hold whole repositories.

Results are grouped by configuration (styre version, variant, model, label); each configuration
gets one table over its results, a total row, its `Stops:` and its run-to-run `Spread:`. With
more than one configuration a final `## Configurations` table compares them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from styre.summarize import count, table  # noqa: E402

HEADER = ["Design", "Started", "New", "Keep", "Phases", "Hours",
          "Uncached in", "Cached in", "Cache hit", "Output", "Prefill h", "Decode h"]


def load_result(path):
    """The `result.json` a PATH names: the file itself, or the directory's own result.json."""
    path = Path(path)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    own = path / "result.json"
    if own.is_file():
        return json.loads(own.read_text(encoding="utf-8"))
    return None


def results_from(path):
    """Every `result.json` one PATH names: a result.json, a directory holding one, or each
    `*/result.json` one level down (never deeper: result directories hold whole repositories).

    Returns `[path, result, ...]`; raises `FileNotFoundError` when it names none."""
    path = Path(path)
    own = load_result(path)
    if own is not None:
        return [(path, own)]
    if not path.is_dir():
        raise FileNotFoundError(path)
    out = []
    for child in sorted(path.iterdir()):
        if child.is_dir():
            res = load_result(child)
            if res is not None:
                out.append((child, res))
    if not out:
        raise FileNotFoundError(path)
    return out


def config_key(result):
    """The group a result belongs to: styre version, variant, model and label."""
    m = result.get("model") or {}
    return (result.get("styre"), result.get("variant"), m.get("provider"), m.get("id"),
            m.get("context_window"), m.get("thinking"), result.get("label"))


def config_name(key):
    """The heading for a configuration, leaving out what is null, such as
    `styre 0.25.0, brief, splash/mlx-community/Qwen3.8-27B-4bit, 120,000 ctx, splash 0.4`."""
    styre, variant, provider, model_id, ctx, _thinking, label = key
    parts = []
    if styre:
        parts.append(f"styre {styre}")
    if variant:
        parts.append(variant)
    if provider and model_id:
        parts.append(f"{provider}/{model_id}")
    if ctx:
        parts.append(f"{count(ctx)} ctx")
    if label:
        parts.append(label)
    return ", ".join(parts)


def served_line(result):
    """A `served: ...` line when the run called a different model than the configuration."""
    m = result.get("model") or {}
    expected = f"{m.get('provider')}/{m.get('id')}"
    served = result.get("served")
    if served and served != expected:
        return f"served: {served}"
    return None


def pair_cell(passed_total):
    """A `15/17 (88%)` cell for a `[passed, total]` pair, or `n/a` when never reached."""
    if not passed_total or passed_total[1] is None:
        return "n/a"
    passed, total = passed_total
    return f"{passed}/{total} ({passed / total:.0%})" if total else "0/0"


def plain_pair_cell(passed_total):
    """A `9/9` cell for a `[passed, total]` pair, or `n/a` when never reached."""
    if not passed_total or passed_total[1] is None:
        return "n/a"
    return f"{passed_total[0]}/{passed_total[1]}"


def token_cells(usage):
    """The `Uncached in`, `Cached in`, `Cache hit` and `Output` cells for a usage block."""
    if usage is None:
        return ["n/a", "n/a", "-", "n/a"]
    uncached, cached, output = usage.get("input"), usage.get("cache_read"), usage.get("output")
    prompt = (uncached or 0) + (cached or 0)
    hit = f"{cached / prompt:.1%}" if prompt else "-"
    return [count(uncached), count(cached), hit, count(output)]


def hours_cell(hours):
    return "n/a" if hours is None else f"{hours:.2f}"


def seconds_cell(seconds):
    """An hours-of-model-time cell for a seconds total: `1.0`, or `n/a` when none was measured."""
    if not seconds:
        return "n/a"
    return f"{seconds / 3600:.1f}"


def result_row(result):
    """The table row for one result; an error sits in the New cell in place of the numbers."""
    u = result.get("usage")
    row = [result.get("design"), result.get("started")]
    if result.get("error"):
        row += [result["error"]] + ["-"] * (len(HEADER) - 3)
        return row
    row += [pair_cell(result.get("new")), plain_pair_cell(result.get("keep")),
            f"{result.get('committed')}/{result.get('phases')}"
            if result.get("phases") is not None else "n/a",
            hours_cell(result.get("hours"))]
    row += token_cells(u)
    row += [seconds_cell(u.get("prefill_seconds") if u else None),
            seconds_cell(u.get("decode_seconds") if u else None)]
    return row


def sum_token_cells(usage_list):
    """The total row's token cells: sums over the usage blocks, hit rate over the summed tokens."""
    usage_list = [u for u in usage_list if u is not None]
    if not usage_list:
        return ["n/a", "n/a", "-", "n/a"]
    uncached = sum(u.get("input") or 0 for u in usage_list)
    cached = sum(u.get("cache_read") or 0 for u in usage_list)
    output = sum(u.get("output") or 0 for u in usage_list)
    prompt = uncached + cached
    hit = f"{cached / prompt:.1%}" if prompt else "-"
    return [count(uncached), count(cached), hit, count(output)]


def sum_seconds_cell(values):
    seconds = sum(v or 0 for v in values)
    return seconds_cell(seconds)


def total_row(results):
    """The table's total row: sums with the overall percentage; a failed result adds nothing."""
    ok = [r for r in results if not r.get("error")]
    new_p = sum((r.get("new") or [0, 0])[0] for r in ok if r.get("new"))
    new_t = sum((r.get("new") or [0, 0])[1] for r in ok if r.get("new"))
    keep_p = sum((r.get("keep") or [0, 0])[0] for r in ok if r.get("keep"))
    keep_t = sum((r.get("keep") or [0, 0])[1] for r in ok if r.get("keep"))
    phases_c = sum(r.get("committed") or 0 for r in ok)
    phases_t = sum(r.get("phases") or 0 for r in ok)
    hours = sum(r.get("hours") or 0 for r in ok)
    usages = [r.get("usage") for r in ok]
    row = ["Total", "-"]
    row += [pair_cell([new_p, new_t]), plain_pair_cell([keep_p, keep_t]),
            f"{phases_c}/{phases_t}", f"{hours:.2f}"]
    row += sum_token_cells(usages)
    row += [sum_seconds_cell([u.get("prefill_seconds") if u else None for u in usages]),
            sum_seconds_cell([u.get("decode_seconds") if u else None for u in usages])]
    return row


def spread_lines(results):
    """One line per design with two or more results in this configuration: the run-to-run
    noise any difference between configurations has to beat."""
    by_design = {}
    for r in results:
        by_design.setdefault(r.get("design"), []).append(r)
    lines = []
    for design in sorted(by_design):
        group = by_design[design]
        if len(group) < 2:
            continue
        entries = [r["new"] for r in group if r.get("new")]
        news = ", ".join(f"{n[0]}" for n in entries)
        totals = {n[1] for n in entries if n[1] is not None}
        if len(totals) == 1 and next(iter(totals)) is not None:
            news += f" of {next(iter(totals))}"
        hours = ", ".join(hours_cell(r["hours"]) for r in group if r.get("hours") is not None)
        line = f"- {design}: new {news}"
        if hours:
            line += f"; hours {hours}"
        lines.append(line)
    return lines


def stops_lines(results):
    """One line per result whose `stopped` or `error` is set."""
    lines = []
    for r in sorted(results, key=lambda r: (r.get("design"), r.get("started") or "")):
        for field in ("stopped", "error"):
            if r.get(field):
                lines.append(f"- {r.get('design')}: {r[field]}")
    return lines


def config_table(entries):
    """The `## Configurations` table, one row per `key, group` pair."""
    header = ["Configuration", "Results", "Designs", "New", "Regressions",
              "Hours", "Uncached in", "Cache hit"]
    rows = [config_table_row(key, group) for key, group in entries]
    return ["## Configurations", "", table(header, rows)]


def config_table_row(key, group):
    """One row: totals only comparable over the same designs, so `Designs` lists them."""
    results = [r for _, r in group]
    ok = [r for r in results if not r.get("error")]
    new_p = sum((r.get("new") or [0, 0])[0] for r in ok if r.get("new"))
    new_t = sum((r.get("new") or [0, 0])[1] for r in ok if r.get("new"))
    regressions = sum(len(r.get("regressions") or []) for r in ok)
    hours = sum(r.get("hours") or 0 for r in ok)
    uncached = sum((r.get("usage") or {}).get("input") or 0 for r in ok if r.get("usage"))
    cached = sum((r.get("usage") or {}).get("cache_read") or 0 for r in ok if r.get("usage"))
    prompt = uncached + cached
    hit = f"{cached / prompt:.1%}" if prompt else "-"
    designs = ", ".join(sorted({r.get("design") for r in results if r.get("design")}))
    return [config_name(key), len(results), designs,
            f"{new_p}/{new_t} ({new_p / new_t:.0%})" if new_t else "n/a",
            regressions, f"{hours:.2f}", count(uncached), hit]


def render(paths):
    """The full report for the PATHs, as one string of markdown lines."""
    results = []
    for path in paths:
        results.extend(results_from(path))
    groups = {}
    for path, result in results:
        groups.setdefault(config_key(result), []).append((path, result))
    lines = ["# Benchmark report", ""]
    for key in sorted(k for k in groups if any(p is not None for p in k)):
        group = sorted(groups[key], key=lambda pr: (pr[1].get("design") or "",
                                                    pr[1].get("started") or ""))
        lines += [f"## {config_name(key)}", ""]
        for _path, result in group:
            s = served_line(result)
            if s:
                lines += [s, ""]
        rows = [result_row(r) for _, r in group] + [total_row([r for _, r in group])]
        lines += [table(HEADER, rows), ""]
        stops = stops_lines([r for _, r in group])
        if stops:
            lines += ["Stops:"] + stops + [""]
        spread = spread_lines([r for _, r in group])
        if spread:
            lines += ["Spread:"] + spread + [""]
    if len(groups) > 1:
        lines += config_table([(k, groups[k]) for k in sorted(groups)])
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def main(argv=None):
    """Read the PATHs' result files, print the report; return 0 on success, 1 otherwise."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 1
    try:
        print(render(argv), end="")
    except FileNotFoundError as e:
        print(f"no result.json under {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
