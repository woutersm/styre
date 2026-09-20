"""Command line interface: the `check` and `run` subcommands."""
import argparse
import sys
from pathlib import Path

from styre import __version__
from styre.config import DEFAULT_GATE_TIMEOUT, DEFAULT_RETRIES, DEFAULT_TIMEOUT, RunOptions
from styre.design import describe, parse_phases, validate
from styre.runner import PreflightError, orchestrate, preflight

EXAMPLES = """examples:
  styre check design.md                 validate the design and print what it will run
  styre run design.md                   run every phase, one commit each
  styre run design.md --from-phase 2    resume after a stop

Run it from inside the target repository: styre switches branches and commits there.
"""


def load_design(path):
    """Read and parse a design file. Exits with a message if it cannot be used."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        sys.exit(f"Could not read the design file: {e}")
    phases = parse_phases(text)
    if not phases:
        sys.exit("No '## Phase N: ...' headings found in the design file.")
    return phases


def cmd_check(args):
    phases = load_design(args.design)
    problems = validate(phases)
    print(describe(phases))
    print("\n" + ("Problems:\n  " + "\n  ".join(problems) if problems else
                  "Design looks runnable. Read the criteria and gates before you approve."))
    return 1 if problems else 0


def cmd_run(args):
    phases = load_design(args.design)
    problems = validate(phases)
    if problems:
        sys.exit("Fix the design first (run 'styre check'):\n  " + "\n  ".join(problems))
    if args.from_phase < 1 or args.from_phase > len(phases):
        sys.exit(f"--from-phase must be between 1 and {len(phases)}.")
    opts = RunOptions(
        quiet=args.quiet, retries=args.retries, timeout=args.timeout,
        gate_timeout=args.gate_timeout, allow_test_changes=args.allow_test_changes,
        from_phase=args.from_phase, branch=args.branch, allow_dirty=args.allow_dirty,
        reset_branch=args.reset_branch,
    )
    try:
        preflight(args.design, opts)
    except PreflightError as e:
        sys.exit(str(e))
    return orchestrate(args.design, phases, opts)


def build_parser():
    ap = argparse.ArgumentParser(
        prog="styre",
        description="Run a phased design through the pi coding agent, one fresh process per phase.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXAMPLES)
    ap.add_argument("--version", action="version", version=f"styre {__version__}")
    sub = ap.add_subparsers(dest="command", metavar="<command>")

    check = sub.add_parser("check", help="print phases, criteria and gates, then exit")
    check.add_argument("design", help="the design document")
    check.set_defaults(func=cmd_check)

    run = sub.add_parser("run", help="run the design, one commit per phase")
    run.add_argument("design", help="the design document")
    run.add_argument("--from-phase", type=int, default=1, metavar="N", help="resume at phase N")
    run.add_argument("--retries", type=int, default=DEFAULT_RETRIES,
                     help=f"fix rounds per phase after a failed gate (default {DEFAULT_RETRIES})")
    run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, metavar="SECONDS",
                     help=f"seconds per pi run, 0 disables (default {DEFAULT_TIMEOUT})")
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
    run.set_defaults(func=cmd_run)
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
