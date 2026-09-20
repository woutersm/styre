#!/usr/bin/env python3
"""Deprecated entry point, kept so existing invocations keep working.

The orchestrator now lives in the `styre` package:

    styre run design.md                  # or: python -m styre run design.md
    styre check design.md
    styre run design.md --from-phase 2
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # work uninstalled too

from styre.cli import main  # noqa: E402


def translate(argv):
    """Map the old `orchestrate.py design.md [--check] [flags]` form onto the subcommands."""
    argv = list(argv)
    if "--check" in argv:
        design = next((a for a in argv if not a.startswith("-")), None)
        return ["check"] + ([design] if design else [])
    return ["run"] + argv


if __name__ == "__main__":
    print("[styre] orchestrate.py is deprecated; use 'styre run <design>'.", file=sys.stderr)
    sys.exit(main(translate(sys.argv[1:])))
