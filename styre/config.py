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

# The pi extensions styre loads into every pi process with --extension, shipped in this package
# so they are versioned with the loop that relies on them (styre/pi_extensions/):
#   cap-output.js      caps a read/bash result when it enters the context
#   no-compaction.js   cancels pi's own compaction; styre restarts a full phase instead
#   strip-thinking.js  drops earlier thinking from every request
PI_EXTENSIONS = tuple(sorted((Path(__file__).parent / "pi_extensions").glob("*.js")))

# Context management, as fractions of the contextWindow in styre's pi config: what the agent
# is told it has, and so what the model host was sized for. Fractions, not token counts, so
# the numbers move with the config instead of being one host's facts.
# - A step whose context passes RELAY_FRACTION is stopped at the end of its current turn and
#   the phase continues in a fresh process from the agent's progress file. 0.75 of 120k is
#   90k. It was 0.6, set from mlxserve's decay curve; on modelhost (2026-09-29, four phases, 900
#   messages) writing flattens at 26-27 tok/s from 40k to 80k and prefill per message stays
#   ~8 s, so staying costs little while every fresh start re-reads its way in. What is left
#   of the reason is the host's memory wall, which modelhost cleared at 96k in model-bench.
# - A fix round resumes the failed step's own session when that step ended below
#   RESUME_FRACTION: its conversation is still in the server's prompt cache, so a small fix
#   costs a minute instead of a fresh process re-reading the phase. Above it, a fresh start.
RELAY_FRACTION = 0.75
RESUME_FRACTION = 0.5
# A phase keeps relaying while each fresh start changes something — the tree or the progress
# file — and stops at the first that changes neither. MAX_RELAYS is only the backstop. It was
# the whole rule at 3, and two phases that were progressing fine finished on exactly their
# third fresh start (app sources 6 and 7, 2026-09-29).
MAX_RELAYS = 6

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
    claude_review: bool = False  # opt-in: one read-only Claude review of the run's commits
