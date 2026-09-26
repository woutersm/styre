"""Constants and the option bundle threaded through a run.

Nothing here is configurable that has only one sensible value: the pi invocation in
particular is a constant because the event parsing requires `--mode json`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PI = ["pi", "-p", "--mode", "json"]  # json mode is not optional: we parse the event stream

# pi's config directory for a styre run, exported to every pi process. An unattended run
# must not inherit an interactive setup: measured on 2026-09-23, the operator's own config
# put 11,551 chars of `pi-web-access` tool schemas and a 10,888-char writing-style
# AGENTS.md into *every request of every turn* — 47% of a phase's starting context, for an
# agent with no network tests and no human reading its prose. It also pins down a hazard
# this file already warned about: PI_CODING_AGENT_DIR is exported from ~/.zshrc, so a run
# started by cron or launchd fell back to the dead pre-16-September ~/.pi/agent tree.
# Keep it lean: models.json, auth.json, a settings.json with no packages, and no AGENTS.md.
# $STYRE_PI_CONFIG_DIR exists so the test suite can point at a temporary directory instead
# of the developer's home; it is not a user-facing knob and `run` has no flag for it.
PI_CONFIG_DIR = Path(os.environ.get("STYRE_PI_CONFIG_DIR")
                     or Path.home() / ".config" / "pi" / "styre")
# --output-format json gives one parseable object with `result`, `is_error`, `total_cost_usd`.
# --dangerously-skip-permissions is required for unattended tool use (verified 2026-09-21:
# --permission-mode acceptEdits still denies Bash outright); see CLAUDE.md's "supervising
# layer" section for why that is an accepted risk here and not elsewhere.
CLAUDE = ["claude", "-p", "--output-format", "json", "--dangerously-skip-permissions"]
WORK = Path(".styre")
DECISIONS = Path("docs/decisions.md")  # committed with the code: the durable record
AGENTS = Path("AGENTS.md")             # pi discovers this automatically, every run
BEGIN, END = "<!-- styre:begin -->", "<!-- styre:end -->"
EXCLUDES = [".styre/", "__pycache__/", ".pytest_cache/", ".ruff_cache/", "*.pyc", "node_modules/", ".venv/"]

DEFAULT_RETRIES = 2
# Seconds of *silence* allowed from pi, not total runtime — see process._watch_idle. It
# stays in hours rather than minutes because pi emits nothing at all for the length of a
# single tool call, so a long test suite inside a phase must not read as a dead link.
DEFAULT_TIMEOUT = 7200
DEFAULT_GATE_TIMEOUT = 900


@dataclass
class RunOptions:
    """Everything the phase loop needs from the command line."""

    quiet: bool = False
    retries: int = DEFAULT_RETRIES
    timeout: int = DEFAULT_TIMEOUT
    gate_timeout: int = DEFAULT_GATE_TIMEOUT
    allow_test_changes: bool = False
    from_phase: int = 1
    run_id: str | None = None
    branch: str | None = None
    allow_dirty: bool = False
    reset_branch: bool = False
    claude_touch: bool = False  # opt-in: real, automatic spend against the Claude CLI
