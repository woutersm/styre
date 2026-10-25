"""Run one benchmark design from start to score, and score its reference test suite.

    python evals/bench.py <design-dir> [--variant brief|full] [--styre CMD] [--pi-config DIR]
                          [--label TEXT] [--out DIR]

`<design-dir>` holds `bench.json` (the design, the reference suite, the checked counts), the
design files and the reference suite. `read_junit` and `score` read the junit XML the design's
own runner writes; `run_bench` clones the design's start commit into a history-less copy, puts
the design in it, runs `<styre> run` through the real runner, resets the tree to the committed
work, runs the reference suite, and records one `result.json` per setup.
"""
from __future__ import annotations

import fnmatch
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from styre.config import EXCLUDES  # noqa: E402

DEFAULT_OUT_NAME = "results"
REF_TIMEOUT = 900   # seconds allowed per reference-suite part


def pi_config_dir(explicit=None):
    """The pi config directory a run uses, as a `Path`.

    `explicit` (a `--pi-config` value or a `pi_config` key in bench.json) wins; otherwise
    `$STYRE_PI_CONFIG_DIR` read at call time, otherwise the developer's `~/.config/pi/styre`.
    """
    return Path(explicit or os.environ.get("STYRE_PI_CONFIG_DIR")
                or Path.home() / ".config" / "pi" / "styre").expanduser()


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


def run(args, cwd, shell=False, env=None, timeout=None, log=None, check=False):
    """Run one command in `cwd`, appending its output to `log`; return (returncode, output).

    `args` is a list of words, or a single shell string when `shell` is set. `check` raises
    RuntimeError on a non-zero exit.
    """
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [args] if shell else list(args)
    try:
        p = subprocess.run(cmd, shell=shell, cwd=str(cwd), env=env, timeout=timeout,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                           errors="replace")
    except FileNotFoundError as e:
        text, rc = f"command not found: {e}", 127
    except subprocess.TimeoutExpired as e:
        out = e.output or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        text, rc = f"{out}\ntimed out after {timeout} s\n", 124
    else:
        text, rc = (p.stdout or ""), p.returncode
    label = " ".join(map(str, cmd))
    if log is not None:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"$ {label}\n{text}")
    if check and rc != 0:
        raise RuntimeError(f"{label} exited {rc}: {text.strip()}")
    return rc, text


def styre_version(styre_cmd, cwd):
    """The last word of `<styre> --version`, or None."""
    _, out = run(shlex.split(styre_cmd) + ["--version"], cwd=cwd)
    words = out.split()
    return words[-1] if words else None


def read_model(config_dir):
    """The default model's provider, id, base_url, contextWindow and thinkingLevel, each None
    when the config does not say. Read the same way `styre.config.context_window` does."""
    out = {"provider": None, "id": None, "base_url": None, "context_window": None, "thinking": None}
    try:
        settings = json.loads((config_dir / "settings.json").read_text(encoding="utf-8"))
        providers = json.loads((config_dir / "models.json").read_text(encoding="utf-8"))["providers"]
    except (OSError, ValueError, KeyError):
        return out
    out["provider"] = settings.get("defaultProvider")
    out["id"] = settings.get("defaultModel")
    out["thinking"] = settings.get("defaultThinkingLevel")
    try:
        entry = providers[settings["defaultProvider"]]
        out["base_url"] = entry.get("baseUrl")
        model = next(m for m in entry.get("models", []) if m.get("id") == settings.get("defaultModel"))
        out["context_window"] = model.get("contextWindow")
    except (KeyError, TypeError, StopIteration):
        pass
    return out


def read_setup(config_dir):
    """The config directory's `setup.json`: what the pi config cannot say (hardware, server,
    engine, quant, speculative decoding), written by hand once per setup. None when absent
    or unreadable. pi ignores the file."""
    try:
        setup = json.loads((Path(config_dir) / "setup.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return setup if isinstance(setup, dict) else None


def _git(repo, *args, check=True):
    return run(["git", *args], cwd=repo, check=check)


def clean_copy(repo_dir, design_dir, start):
    """A clean copy of `start` with no history: clone, detach, re-init, one start commit, and
    styre's own excludes in `.git/info/exclude` so setup's dependency folders never dirty it.
    Returns the copy path."""
    (design_dir / "repo").mkdir(parents=True)
    run(["git", "clone", "--quiet", str(Path(repo_dir).expanduser()), "repo"],
        cwd=design_dir, check=True)
    repo = design_dir / "repo"
    _git(repo, "checkout", "--quiet", start)
    shutil.rmtree(repo / ".git")
    _git(repo, "init", "--quiet", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", f"bench: start {start[:7]}")
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    have = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
    with open(exclude, "a", encoding="utf-8") as f:
        f.writelines(p + "\n" for p in EXCLUDES if p not in have)
    return repo


def copy_design(design, design_dir, repo, variant):
    """Copy `designs[variant]` over `design_path`; commit it when that changed the tree."""
    src = design_dir / design["designs"][variant]
    (repo / design["design_path"]).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, repo / design["design_path"])
    if _git(repo, "status", "--porcelain")[1].strip():
        _git(repo, "add", "-A")
        _git(repo, "commit", "--quiet", "-m", f"bench: {variant} design")


def do_setup(design, repo, setup_log):
    """Run each `setup` command in the copy. Return a one-sentence error, or None when clean."""
    for cmd in design.get("setup") or []:
        rc, _ = run(cmd, cwd=repo, shell=True, log=setup_log)
        if rc != 0:
            return f"setup command `{cmd}` exited {rc}"
    if _git(repo, "status", "--porcelain")[1].strip():
        return "setup left the working tree dirty"
    return None


def do_run(design, repo, styre_cmd, config_dir, styre_log):
    """Run `<styre> run <design_path>` in the copy. Return (exit_code, hours)."""
    env = {**os.environ, "STYRE_PI_CONFIG_DIR": str(config_dir), "NO_COLOR": "1"}
    started = time.time()
    rc, _ = run(shlex.split(styre_cmd) + ["run", design["design_path"]], cwd=repo, env=env,
                log=styre_log)
    return rc, round((time.time() - started) / 3600, 2)


def read_run(summary, run_root):
    """`committed`, `stopped` and `served` from one collected run, each None when absent."""
    from styre.summarize import read_events

    committed = sum(1 for p in summary.phases if p.status == "committed")
    stopped = summary.last.get("stopped")
    served = None
    for p in summary.phases:
        path = run_root / "logs" / f"phase{p.n}.events.jsonl"
        for e in read_events(path):
            message = e.get("message") or {}
            if e.get("type") == "message_start" and message.get("provider") and message.get("model"):
                served = f"{message['provider']}/{message['model']}"
                break
        if served:
            break
    return committed, stopped, served


def do_reference(design, design_dir, repo, junit_dir):
    """Run the reference suite's parts in the copy; return the score dict and the parts list."""
    ref = design.get("reference") or {}
    keep_glob = ref.get("keep", "test_keep_*")
    checked = (design.get("checked") or {}).get("start") or {}
    new = (checked.get("new") or [0, 0])[1]
    keep = (checked.get("keep") or [0, 0])[1]
    cases, parts = [], []
    for i, part in enumerate(ref.get("parts") or []):
        src = design_dir / part["dir"]
        shutil.copytree(src, repo / part["into"], dirs_exist_ok=True)
        xml = junit_dir / f"part{i}.xml"
        cmd = part["command"].replace("{junit}", str(xml))
        rc, _ = run(cmd, cwd=repo, shell=True, timeout=REF_TIMEOUT)
        cases += read_junit(xml)
        parts.append({"command": part["command"], "rc": rc,
                      "junit": str(xml) if xml.exists() else None})
    return score(cases, keep_glob, new, keep), parts


def usage_of(summary):
    """The `usage` block: every metric summed over phases, `peak` the largest."""
    usage = {k: 0 for k in ("requests", "input", "cache_read", "output", "peak",
                            "prefill_seconds", "decode_seconds", "agent_seconds", "gate_seconds")}
    for p in summary.phases:
        u = p.usage
        usage["requests"] += u.requests
        usage["input"] += u.input
        usage["cache_read"] += u.cache_read
        usage["output"] += u.output
        usage["peak"] = max(usage["peak"], u.peak or 0)
        usage["prefill_seconds"] += u.prefill_seconds
        usage["decode_seconds"] += u.decode_seconds
        usage["agent_seconds"] += p.agent_seconds
        usage["gate_seconds"] += p.gate_seconds
    return usage


def run_bench(design_dir, variant, styre_cmd, out, pi_config=None, label=None):
    """Run one benchmark design end to end and write `result.json`. Returns the result dict.

    `pi_config` (the pi config directory the run uses) and `label` (free text for what the
    config cannot show) default to the values in `bench.json`, or None. Keys a failed run
    never reached stay null.
    """
    from styre.rundir import RunDir
    from styre.summarize import collect

    design_dir = Path(design_dir).resolve()
    design = json.loads((design_dir / "bench.json").read_text(encoding="utf-8"))
    if pi_config is not None:
        design["pi_config"] = pi_config
    if label is not None:
        design["label"] = label
    config_dir = pi_config_dir(design.get("pi_config"))
    out = Path(out)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    result_dir = out / f"{design_dir.name}-{variant}-{stamp}"
    result_dir.mkdir(parents=True, exist_ok=True)
    repo = result_dir / "repo"
    junit_dir = result_dir / "junit"
    setup_log = result_dir / "setup.log"
    styre_log = result_dir / "styre.log"
    result = {
        "design": design_dir.name, "variant": variant, "styre": None,
        "label": design.get("label"), "setup": read_setup(config_dir),
        "model": read_model(config_dir), "served": None,
        "start": design.get("start"), "started": datetime.now().astimezone().isoformat(),
        "hours": None, "exit_code": None, "run_id": None, "phases": design.get("phases"),
        "committed": None, "stopped": None, "error": None,
        "new": None, "keep": None, "failing": None, "regressions": None, "missing": None,
        "parts": None, "usage": None,
    }
    try:
        clean_copy(design["repo"], result_dir, design["start"])
        copy_design(design, design_dir, repo, variant)
        result["error"] = do_setup(design, repo, setup_log)
        if result["error"] is None:
            result["styre"] = styre_version(styre_cmd, repo)
            rc, hours = do_run(design, repo, styre_cmd, config_dir, styre_log)
            result["exit_code"], result["hours"] = rc, hours
            result["run_id"] = (repo / ".styre" / "latest.txt").read_text(encoding="utf-8").strip()
            run_id = result["run_id"]
            run_root = repo / ".styre" / "runs" / run_id
            summary = collect(RunDir(run_root))
            committed, stopped, served = read_run(summary, run_root)
            result["committed"], result["stopped"], result["served"] = committed, stopped, served
            result["usage"] = usage_of(summary)
            # Only committed work is scored: reset to the start, which removes untracked files
            # the run left (done.txt) while the excluded .styre/ and dependency folders survive.
            _git(repo, "reset", "--quiet", "--hard")
            _git(repo, "clean", "-fdq")
            junit_dir.mkdir(parents=True, exist_ok=True)
            sc, parts = do_reference(design, design_dir, repo, junit_dir)
            result.update(sc)
            result["parts"] = parts
    except Exception as e:  # the run is recorded even when an earlier step blew up
        import traceback

        traceback.print_exc()
        result["error"] = result.get("error") or f"{type(e).__name__}: {e}"
    (result_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    result["_dir"] = str(result_dir / "result.json")
    return result


def main(argv=None):
    """Run one benchmark design and print one summary line; return 0 when `error` is null."""
    import argparse

    ap = argparse.ArgumentParser(prog="bench",
                                 description="Run one benchmark design from start to score.")
    ap.add_argument("design_dir", help="the design directory, holding bench.json")
    ap.add_argument("--variant", default="brief", choices=["brief", "full"])
    ap.add_argument("--styre", default="styre", help="the styre command (shlex-split)")
    ap.add_argument("--pi-config", default=None, help="the pi config directory for the run")
    ap.add_argument("--label", default=None, help="free text for what the config cannot show")
    ap.add_argument("--out", default=None,
                    help="results root (default <design-dir>/../results)")
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    out = args.out or str(Path(args.design_dir).resolve().parent / DEFAULT_OUT_NAME)
    result = run_bench(args.design_dir, args.variant, args.styre, out,
                       pi_config=args.pi_config, label=args.label)
    new, keep = result["new"] or [None, None], result["keep"] or [None, None]
    print(f"{result['design']} {result['variant']}: new {new[0]}/{new[1]}, "
          f"keep {keep[0]}/{keep[1]}, {result['committed']}/{result['phases']} phases "
          f"committed, {result['hours']} h -> {result.get('_dir')}")
    return 0 if result["error"] is None else 1


if __name__ == "__main__":
    sys.exit(main())
