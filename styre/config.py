"""Constants and the option bundle threaded through a run.

Nothing here is configurable that has only one sensible value: the pi invocation in
particular is a constant because the event parsing requires `--mode json`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PI = ["pi", "-p", "--mode", "json"]  # json mode is not optional: we parse the event stream
WORK = Path(".styre")
DECISIONS = Path("docs/decisions.md")  # committed with the code: the durable record
AGENTS = Path("AGENTS.md")             # pi discovers this automatically, every run
BEGIN, END = "<!-- styre:begin -->", "<!-- styre:end -->"
EXCLUDES = [".styre/", "__pycache__/", ".pytest_cache/", ".ruff_cache/", "*.pyc", "node_modules/", ".venv/"]

DEFAULT_RETRIES = 2
DEFAULT_TIMEOUT = 5400
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
    branch: str | None = None
    allow_dirty: bool = False
    reset_branch: bool = False
