"""Do `styre check`'s warnings predict the phases that go badly?

Replays `advisories()` over every design a repository has run, recovered from its git history
by the hash each run recorded, and scores each kind of warning against what the phase then
did: precision (a flagged phase went badly), recall (a phase that went badly was flagged).

    python evals/advisories.py ~/Dev/some-repo > evals/results/advisories.md

A phase is one (design version, phase number); its attempts across runs and resumes are
pooled. It went badly ("trouble") when any attempt was stopped for a reason a design can
cause, or needed a fresh start because its context filled. A phase whose only stops are pi
being killed or crashing is left out: that says nothing about the design.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from styre.design import advisories, parse_phases, phase_context  # noqa: E402
from styre.prompts import build_prompt  # noqa: E402
from styre.rundir import RunDir  # noqa: E402
from styre.summarize import collect  # noqa: E402

INFRA = re.compile(r"^pi exited")
# Each warning, by the words it starts with, and how to read the phases it names.
KINDS = [
    ("preamble names documents", re.compile(r"^The preamble names"), "all"),
    ("asks for a skipped test", re.compile(r"^Phase (\d+) asks for a skipped test"), "one"),
    ("names a document", re.compile(r"^Phase (\d+) names"), "one"),
    ("large phase", re.compile(r"^Phase (\d+) is large"), "one"),
    ("two toolchains", re.compile(r"^Phase\(s\) ([\d, ]+) are gated"), "list"),
    ("new library, no example", re.compile(r"^Phase (\d+) uses"), "one"),
]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout


def find_design(repo, path, sha16):
    """The design text whose sha256 starts with `sha16`, and the commit that holds it."""
    for commit in git(repo, "log", "--all", "--format=%H", "--", path).split():
        text = git(repo, "show", f"{commit}:{path}")
        if hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] == sha16:
            return text, commit
    return None, None


def manifests(repo, commit, into):
    """The dependency manifests as they were at `commit`, for `installed()`."""
    for name in git(repo, "ls-tree", "-r", "--name-only", commit).splitlines():
        if name == "pyproject.toml" or re.fullmatch(r"(?:[^/]+/)?package\.json", name):
            target = into / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(git(repo, "show", f"{commit}:{name}"), encoding="utf-8")


def flagged(text, design_path, root):
    """{kind: set of phase numbers} for one design."""
    phases = parse_phases(text)
    sizes = [len(build_prompt(phase_context(text, phases, n), n, p, ""))
             for n, p in enumerate(phases, 1)]
    out = defaultdict(set)
    for note in advisories(text, phases, sizes, design_path, root=root):
        for kind, pattern, how in KINDS:
            m = pattern.match(note)
            if not m:
                continue
            if how == "all":
                out[kind] |= set(range(1, len(phases) + 1))
            elif how == "one":
                out[kind].add(int(m.group(1)))
            else:
                out[kind] |= {int(x) for x in m.group(1).replace(" ", "").split(",") if x}
    return out, len(phases)


def outcomes(run_root):
    """{phase: (trouble, stopped, infra_only, peak)} for one run directory, from its timeline."""
    events = [json.loads(line) for line in (run_root / "timeline.jsonl").read_text().splitlines()
              if line.strip()]
    peaks = {p.n: p.usage.peak for p in collect(RunDir(run_root)).phases}
    seen = defaultdict(lambda: {"trouble": False, "design_stop": False, "infra": False})
    for e in events:
        if e.get("event") != "phase_end":
            continue
        s = seen[e["phase"]]
        if e.get("relays"):
            s["trouble"] = True
        if e.get("status") != "committed":
            if INFRA.match(e.get("reason") or ""):
                s["infra"] = True
            else:
                s["trouble"] = s["design_stop"] = True
    return {n: (s["trouble"], s["design_stop"], s["infra"] and not s["trouble"], peaks.get(n, 0))
            for n, s in seen.items()}


def main(repo):
    repo = Path(repo).expanduser().resolve()
    designs = {}   # (path, sha16) -> {"text", "commit", "phases": {n: [trouble, stopped, peak]}}
    skipped = []
    for run_root in sorted((repo / ".styre" / "runs").iterdir()):
        timeline = run_root / "timeline.jsonl"
        start = next((json.loads(line) for line in timeline.read_text().splitlines()
                      if '"run_start"' in line), None) if timeline.is_file() else None
        if not start or not start.get("design_sha256"):
            skipped.append((run_root.name, "no run_start with a design hash"))
            continue
        key = (start["design"], start["design_sha256"])
        if key not in designs:
            text, commit = find_design(repo, start["design"], start["design_sha256"])
            if text is None:
                skipped.append((run_root.name, f"{start['design']} not found in git history"))
                continue
            designs[key] = {"text": text, "commit": commit, "phases": {}}
        for n, (trouble, stopped, infra_only, peak) in outcomes(run_root).items():
            if infra_only:
                continue
            was = designs[key]["phases"].get(n, [False, False, 0])
            designs[key]["phases"][n] = [was[0] or trouble, was[1] or stopped, max(was[2], peak)]

    rows = []      # (design, phase, trouble, stopped, peak, kinds)
    for (path, _), d in designs.items():
        with tempfile.TemporaryDirectory() as tmp:
            manifests(repo, d["commit"], Path(tmp))
            flags, _ = flagged(d["text"], path, Path(tmp))
        for n, (trouble, stopped, peak) in sorted(d["phases"].items()):
            rows.append((path, n, trouble, stopped, peak,
                         {k for k, ns in flags.items() if n in ns}))

    print(report(rows, skipped, len(designs)))


def ratio(a, b):
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "–"


def report(rows, skipped, n_designs):
    total = len(rows)
    bad = sum(1 for r in rows if r[2])
    stopped = sum(1 for r in rows if r[3])
    out = ["# Do `styre check`'s warnings predict trouble?", "",
           f"{total} phases from {n_designs} design versions, scored two ways:", "",
           f"- **Went badly**: stopped for a design reason, or needed a fresh start for "
           f"context. Base rate {ratio(bad, total)}.",
           f"- **Stopped**: stopped for a design reason, uncommitted. Base rate "
           f"{ratio(stopped, total)}.", "",
           "A warning is useful when its precision beats the base rate. Precision: of the "
           "phases it flagged, how many went that way. Recall: of the phases that went that "
           "way, how many it flagged.", "",
           "| Warning | Flagged | Went badly: precision | recall | Stopped: precision | recall |",
           "| --- | --- | --- | --- | --- | --- |"]
    for kind, _, _ in KINDS + [("any warning", None, None)]:
        hit = [r for r in rows if (r[5] if kind == "any warning" else kind in r[5])]
        tp_bad = sum(1 for r in hit if r[2])
        tp_stop = sum(1 for r in hit if r[3])
        out.append(f"| {kind} | {len(hit)} | {ratio(tp_bad, len(hit))} | {ratio(tp_bad, bad)} "
                   f"| {ratio(tp_stop, len(hit))} | {ratio(tp_stop, stopped)} |")
    peaks = sorted(r[4] for r in rows if r[4])
    if peaks:
        out += ["", f"Peak context per phase: median {peaks[len(peaks) // 2]:,}, "
                f"max {peaks[-1]:,} tokens."]
    out += ["", "## Phases", "",
            "| Design | Phase | Went badly | Stopped | Peak context | Flagged as |",
            "| --- | --- | --- | --- | --- | --- |"]
    out += [f"| `{Path(d).name}` | {n} | {'yes' if t else ''} | {'yes' if s else ''} | {p:,} "
            f"| {', '.join(sorted(k))} |" for d, n, t, s, p, k in rows]
    if skipped:
        out += ["", "## Runs left out", ""] + [f"- `{r}`: {why}" for r, why in skipped]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python evals/advisories.py <repo with .styre/runs>")
    main(sys.argv[1])
