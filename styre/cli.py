"""Command line interface: the `design`, `check`, `plan`, `run` and `summarize` subcommands."""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from styre import __version__, claude, planner
from styre.config import DEFAULT_GATE_TIMEOUT, DEFAULT_RETRIES, DEFAULT_TIMEOUT, RunOptions, context_window
from styre.design import advisories, describe, parse_phases, phase_context, validate
from styre.gitops import add_excludes, commit, is_dirty, not_at_root, stage_all
from styre.planner import PLAN_SCHEMA
from styre.prompts import build_prompt, planner_prompt
from styre.rundir import RUNS, new_run, resolve
from styre.runner import PreflightError, context_budget, orchestrate, preflight
from styre.summarize import collect, compare, history_lines, repo_history, summarize
from styre.timeline import Timeline

EXAMPLES = """examples:
  styre design "CSV export"            write a design with Claude Code (/styre-design)
  styre check design.md                 validate the design and print what it will run
  styre run design.md                   run every phase, one commit each
  styre run design.md --from-phase 2    resume after a stop
  styre summarize                       what happened in the last run
  styre summarize 20260920-233014       ... in a particular one

Run it from the target repository's root: styre switches branches and commits there,
and writes AGENTS.md and .styre/ into the directory it starts in.
"""


def load_design(path):
    """Read and parse a design file. Exits with a message if it cannot be used.

    Returns (text, phases): `check` needs the document itself for the preamble.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        sys.exit(f"Could not read the design file: {e}")
    phases = parse_phases(text)
    if not phases:
        sys.exit("No '## Phase N: ...' headings found in the design file.")
    return text, phases


def cmd_design(args):
    """Open interactive Claude Code on the /styre-design skill.

    A launcher only: the interview, the judgement and the approval stay with the person
    and Claude. styre itself still calls no model.
    """
    if (root := not_at_root()) is not None:
        print(f"Run styre from the repository root, not a subdirectory:\n  cd {root}",
              file=sys.stderr)
        return 1
    claude = shutil.which("claude")
    if claude is None:
        sys.exit("Claude Code ('claude') is not on PATH: https://claude.com/claude-code")
    prompt = " ".join(["/styre-design", *args.idea])
    return subprocess.run([claude, prompt]).returncode


def cmd_plan(args):
    """Ask Claude to add implementation help to a brief, then commit the planned design.

    styre checks the answer kept every line of the brief, writes it over the brief file,
    and commits it. The person reads the change with `git show` and runs `styre run` when
    they agree. A failed call or a brief the answer changed leaves the tree untouched.
    """
    if (root := not_at_root()) is not None:
        print(f"Run styre from the repository root, not a subdirectory:\n  cd {root}",
              file=sys.stderr)
        return 1
    if is_dirty():
        sys.exit("Working tree is not clean. Commit or stash first (plan makes one commit).")
    brief, _phases = load_design(args.design)
    if (problems := validate(_phases)):
        sys.exit("Fix the brief first (run 'styre check'):\n  " + "\n  ".join(problems))

    design_path = Path(args.design)
    add_excludes()
    run = new_run()
    tl = Timeline(run.timeline)
    tl.event("run_start", **{"run": run.id, "styre": __version__,
               "design": str(design_path), "kind": "plan"})
    run_dir = run.root / "logs"

    prompt = planner_prompt(brief, context_window())
    result = claude.call("planner", prompt, PLAN_SCHEMA, ["Read", "Grep", "Glob"],
                         cwd=Path.cwd(), timeline=tl, log_dir=run_dir)
    planned = None
    usage = result.usage
    if result.error is not None:
        tl.event("run_end", exit_code=1, stopped=result.error)
        return 1
    planned = (result.output or {}).get("design")
    if not isinstance(planned, str):
        tl.event("run_end", exit_code=1, stopped="The planner returned no design text.")
        print("The planner returned no design text.")
        return 1

    problems = planner.problems(brief, planned)
    if problems:
        retry = claude.call("planner", prompt + "\n\nYour design was refused:\n" +
                            "\n".join(problems), PLAN_SCHEMA, ["Read", "Grep", "Glob"],
                            cwd=Path.cwd(), timeline=tl, log_dir=run_dir)
        usage = retry.usage
        if retry.error is not None:
            problems = [retry.error]
        else:
            planned = (retry.output or {}).get("design")
            problems = planner.problems(brief, planned) if isinstance(planned, str) else [
                "The planner returned no design text."]
    if problems:
        for sentence in problems:
            print(sentence)
        tl.event("run_end", exit_code=1, stopped=problems[0])
        return 1

    design_path.write_text(planned, encoding="utf-8")
    stage_all()
    stem = design_path.name.rsplit(".", 1)[0]
    if commit(f"Plan: {stem}") != 0:
        tl.event("run_end", exit_code=1, stopped="The planned design could not be committed.")
        return 1
    tl.event("run_end", exit_code=0, stopped=None)
    print(design_path)
    for note in advisories(planned, parse_phases(planned), design_path.name, root=Path.cwd()):
        print(f"  ⚠ {note}")
    print(f"Planner used {usage.tokens_in:,} tokens in, {usage.tokens_out:,} out.")
    print(f"Read it: git show; run it: styre run {design_path}")
    return 0


def cmd_check(args):
    """Validate the design and print what it will run."""
    if (root := not_at_root()) is not None:
        print(f"Run styre from the repository root, not a subdirectory:\n  cd {root}",
              file=sys.stderr)
        return 1
    text, phases = load_design(args.design)
    problems = validate(phases)
    print(describe(phases))
    if problems:
        print("\nProblems:\n  " + "\n  ".join(problems))
        return 1

    sizes = [len(build_prompt(phase_context(text, phases, n), n, p, ""))
             for n, p in enumerate(phases, 1)]
    print("\n--- Prompt size per phase ---")
    for n, (phase, size) in enumerate(zip(phases, sizes), 1):
        print(f"  {n:>3}. {size / 1024:>5.1f} KB  {len(phase.criteria)} criteria  {phase.title}")

    notes = advisories(text, phases, args.design, root=Path.cwd())
    if notes:
        print("\n--- Worth a look before you start ---")
        for note in notes:
            print(f"  ⚠ {note}")

    history = history_lines(repo_history(RUNS), context_budget()[0])
    if history:
        print("\n--- This repository's phases so far ---")
        print("\n".join(f"  {line}" for line in history))

    print("\nDesign looks runnable. Read the criteria and gates before you approve.")
    return 0


def cmd_run(args):
    _, phases = load_design(args.design)
    problems = validate(phases)
    if problems:
        sys.exit("Fix the design first (run 'styre check'):\n  " + "\n  ".join(problems))
    if args.from_phase < 1 or args.from_phase > len(phases):
        sys.exit(f"--from-phase must be between 1 and {len(phases)}.")
    opts = RunOptions(
        quiet=args.quiet, retries=args.retries, timeout=args.timeout,
        gate_timeout=args.gate_timeout, allow_test_changes=args.allow_test_changes,
        from_phase=args.from_phase, run_id=args.run_id, branch=args.branch,
        allow_dirty=args.allow_dirty,
        reset_branch=args.reset_branch,
    )
    try:
        run = preflight(args.design, opts)
    except PreflightError as e:
        sys.exit(str(e))
    return orchestrate(args.design, opts, run)


def cmd_summarize(args):
    if args.run and args.compare:
        sys.exit("Give either a run or --compare A B, not both.")
    if args.compare:
        runs = []
        for name in args.compare:
            run = resolve(name)
            if run is None:
                sys.exit(f"No such run: {name}.")
            runs.append(run)
        # Printed, never written: a comparison is a check, not a record in either run.
        print(compare(collect(runs[0]), collect(runs[1])))
        return 0
    run = resolve(args.run)
    if run is None:
        sys.exit(f"No such run: {args.run}." if args.run else
                 "No runs found under .styre/runs/.")
    print(summarize(run))
    print(f"[styre] written to {run.root / 'summary.md'}")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        prog="styre",
        description="Run a phased design through the pi coding agent, one fresh process per phase.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXAMPLES)
    ap.add_argument("--version", action="version", version=f"styre {__version__}")
    sub = ap.add_subparsers(dest="command", metavar="<command>")

    design = sub.add_parser(
        "design", help="write a design with Claude Code: opens claude on /styre-design")
    design.add_argument("idea", nargs="*", help="what to build, in a sentence (optional)")
    design.set_defaults(func=cmd_design)

    check = sub.add_parser(
        "check", help="validate the design and print its phases, gates and prompt sizes")
    check.add_argument("design", help="the design document")
    check.set_defaults(func=cmd_check)

    plan = sub.add_parser(
        "plan", help="add implementation help to a brief with Claude, and commit it")
    plan.add_argument("design", help="the brief design document")
    plan.set_defaults(func=cmd_plan)

    run = sub.add_parser("run", help="run the design, one commit per phase")
    run.add_argument("design", help="the design document")
    run.add_argument("--from-phase", type=int, default=1, metavar="N", help="resume at phase N")
    run.add_argument("--run-id", default=None, metavar="ID",
                     help="write into .styre/runs/ID (default: a new run, or the latest one "
                          "when resuming with --from-phase)")
    run.add_argument("--retries", type=int, default=DEFAULT_RETRIES,
                     help=f"fix rounds per phase after a failed gate (default {DEFAULT_RETRIES})")
    run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, metavar="SECONDS",
                     help=f"seconds of silence before a pi run is killed, 0 disables "
                          f"(default {DEFAULT_TIMEOUT}); a phase that keeps printing is "
                          f"never cut off")
    run.add_argument("--gate-timeout", type=int, default=DEFAULT_GATE_TIMEOUT, metavar="SECONDS",
                     help=f"seconds per gate command, 0 disables (default {DEFAULT_GATE_TIMEOUT})")
    run.add_argument("--quiet", action="store_true", help="do not echo the agent's output while it works")
    run.add_argument("--allow-test-changes", action="store_true",
                     help="turn off the skipped/removed test guard")
    run.add_argument("--branch", default=None, metavar="NAME",
                     help="run branch (default styre/<design-stem>)")
    run.add_argument("--allow-dirty", action="store_true", help="start with an unclean working tree")
    run.add_argument("--reset-branch", action="store_true",
                     help="discard an existing run branch and restart it at HEAD (destructive)")
    run.set_defaults(func=cmd_run)

    summary = sub.add_parser("summarize", help="report what happened in a run")
    summary.add_argument("run", nargs="?", default=None, metavar="RUN",
                         help="a run id or directory (default: the latest run)")
    summary.add_argument("--compare", nargs=2, metavar=("A", "B"), default=None,
                         help="two runs side by side, per phase")
    summary.set_defaults(func=cmd_summarize)

    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
