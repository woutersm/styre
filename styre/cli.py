"""Command line interface: the `check`, `run`, `summarize` and `watch` subcommands."""
import argparse
import sys
from pathlib import Path

from styre import __version__
from styre.config import DEFAULT_GATE_TIMEOUT, DEFAULT_RETRIES, DEFAULT_TIMEOUT, RunOptions
from styre.design import advisories, describe, parse_phases, phase_context, validate
from styre.prompts import build_prompt
from styre.review import describe_review
from styre.rundir import resolve
from styre.runner import PreflightError, orchestrate, preflight
from styre.summarize import summarize
from styre.watch import DEFAULT_PORT, serve

EXAMPLES = """examples:
  styre check design.md                 validate the design, print what it will run, and
                                        find existing repo code its phases already name
  styre run design.md                   run every phase, one commit each
  styre run design.md --from-phase 2    resume after a stop
  styre summarize                       what happened in the last run
  styre summarize 20260920-233014       ... in a particular one
  styre watch                           read-only web view of this repo's runs, live

Run it from inside the target repository: styre switches branches and commits there.
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


def cmd_check(args):
    """Validate the design, print it, and — once it is structurally runnable — cross-
    reference it against the repository. Both halves answer the same question, "is this
    safe to start tonight", so they are one command rather than two to remember."""
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

    notes = advisories(text, phases, sizes, args.design)
    if notes:
        print("\n--- Worth a look before you start ---")
        for note in notes:
            print(f"  ⚠ {note}")

    print("\n--- What each phase's prose already names in this repository ---")
    print(describe_review(phases))
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
        claude_touch=args.claude_touch,
    )
    try:
        run = preflight(args.design, opts)
    except PreflightError as e:
        sys.exit(str(e))
    return orchestrate(args.design, opts, run)


def cmd_summarize(args):
    run = resolve(args.run)
    if run is None:
        sys.exit(f"No such run: {args.run}." if args.run else
                 "No runs found under .styre/runs/.")
    print(summarize(run))
    print(f"[styre] written to {run.root / 'summary.md'}")
    return 0


def cmd_watch(args):
    """Serve the read-only view. It writes nothing, so there is no --dry-run and no
    confirmation: the only thing it can do is show you the files that are already there."""
    return serve(port=args.port)


def build_parser():
    ap = argparse.ArgumentParser(
        prog="styre",
        description="Run a phased design through the pi coding agent, one fresh process per phase.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXAMPLES)
    ap.add_argument("--version", action="version", version=f"styre {__version__}")
    sub = ap.add_subparsers(dest="command", metavar="<command>")

    check = sub.add_parser(
        "check", help="validate the design, print its phases and gates, and find existing "
                      "repo code each phase's prose already names")
    check.add_argument("design", help="the design document")
    check.set_defaults(func=cmd_check)

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
                     help="run branch (default overnight/<design-stem>)")
    run.add_argument("--allow-dirty", action="store_true", help="start with an unclean working tree")
    run.add_argument("--reset-branch", action="store_true",
                     help="discard an existing run branch and restart it at HEAD (destructive)")
    run.add_argument("--claude-touch", action="store_true",
                     help="on a stop, give Claude (via `claude -p`) one turn at the stuck "
                          "phase before giving up — real, automatic spend against the "
                          "Claude CLI; off by default")
    run.set_defaults(func=cmd_run)

    summary = sub.add_parser("summarize", help="report what happened in a run")
    summary.add_argument("run", nargs="?", default=None, metavar="RUN",
                         help="a run id or directory (default: the latest run)")
    summary.set_defaults(func=cmd_summarize)

    watch = sub.add_parser("watch", help="serve a read-only web view of this repo's runs on "
                                         "localhost, refreshing while a phase runs")
    watch.add_argument("--port", type=int, default=DEFAULT_PORT, metavar="PORT",
                       help=f"port to listen on (default {DEFAULT_PORT})")
    watch.set_defaults(func=cmd_watch)
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
