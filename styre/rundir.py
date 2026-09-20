"""The per-run directory: `.styre/runs/<id>/`.

Everything one run writes goes under one timestamped directory, so two runs can be compared
instead of overwriting each other. `.styre/latest.txt` names the most recent one — a file
rather than a symlink, because Windows.

The agent's own contract does not move. It still writes `.styre/phaseN.state.json` and
`.styre/notes-next.md`, the short stable paths AGENTS.md names; `collect()` moves those two
files into the run directory once the process has stopped. The drop box is the interface,
the run directory is the archive.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from styre.config import WORK

RUNS = WORK / "runs"
LATEST = WORK / "latest.txt"
INBOX_NOTES = WORK / "notes-next.md"


def inbox_state(n):
    """Where the agent writes phase n's state file. Named in AGENTS.md, so it does not move."""
    return WORK / f"phase{n}.state.json"


@dataclass(frozen=True)
class RunDir:
    """One run's directory and the paths inside it."""

    root: Path

    @property
    def id(self):
        return self.root.name

    def prompt(self, n):
        return self.root / f"phase{n}.prompt.md"

    def fix(self, n, round_):
        return self.root / f"phase{n}.fix{round_}.md"

    def log(self, n):
        return self.root / "logs" / f"phase{n}.log"

    def events(self, n):
        return self.root / "logs" / f"phase{n}.events.jsonl"

    def sessions(self, n):
        """Where pi saves phase n's own session files, one per step it runs."""
        return self.root / "sessions" / f"phase{n}"

    def state(self, n):
        return self.root / f"phase{n}.state.json"

    def notes(self, n):
        # Per phase, not one overwritten file: resuming at phase N has to read exactly what
        # phase N-1 handed over, even if a later phase already ran and wrote its own notes.
        return self.root / f"phase{n}.notes-next.md"

    @property
    def timeline(self):
        return self.root / "timeline.jsonl"

    @property
    def report(self):
        return self.root / "report.md"


def _make(root):
    (root / "logs").mkdir(parents=True, exist_ok=True)
    run = RunDir(root)
    LATEST.write_text(run.id + "\n", encoding="utf-8")
    return run


def new_run(now=None):
    """Create `.styre/runs/<YYYYmmdd-HHMMSS>/` and point latest.txt at it."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    root, n = RUNS / stamp, 1
    while root.exists():  # two runs started inside the same second
        n += 1
        root = RUNS / f"{stamp}-{n}"
    return _make(root)


def open_run(run_id):
    """Reopen an existing run by id, or return None if there is no such directory."""
    root = RUNS / run_id
    return _make(root) if root.is_dir() else None


def latest_run():
    """The run latest.txt names, falling back to the newest directory on disk."""
    if LATEST.exists():
        name = LATEST.read_text(encoding="utf-8").strip()
        if name and (RUNS / name).is_dir():
            return RunDir(RUNS / name)
    dirs = sorted((d for d in RUNS.glob("*") if d.is_dir()), key=lambda d: d.name)
    return RunDir(dirs[-1]) if dirs else None


def resolve(name=None):
    """The run a command was pointed at: a directory path, a run id, or — with nothing —
    the latest. Returns None if there is no such run."""
    if not name:
        return latest_run()
    path = Path(name)
    if path.is_dir():
        return RunDir(path)
    return RunDir(RUNS / name) if (RUNS / name).is_dir() else None


def clear_inbox(n):
    """Remove whatever an earlier run or fix round left at the agent's two paths, so a file
    that is not written this time round reads as missing rather than as stale success."""
    inbox_state(n).unlink(missing_ok=True)
    INBOX_NOTES.unlink(missing_ok=True)


def collect(run, n):
    """Move phase n's state and notes out of the drop box into the run directory."""
    for src, dst in ((inbox_state(n), run.state(n)), (INBOX_NOTES, run.notes(n))):
        if src.exists():
            src.replace(dst)
