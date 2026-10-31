"""Write a phase's acceptance files into the working tree before a gate runs.

The files come from the approved design, so they are the ground truth for a phase: a
builder that edits one is undone by the next write, and the difference it left is the
`acceptance_restored` record, not the commit.
"""
from __future__ import annotations

from pathlib import Path


def write(phase, root) -> list[str]:
    """Write each of `phase.acceptance` to its path under `root`, creating parents.

    Returns the paths of the files that already existed with different content, in order.
    A file that did not exist yet is written and not returned.
    """
    edited: list[str] = []
    for path, content in phase.acceptance:
        target = Path(root) / path
        if target.exists():
            with open(target, encoding="utf-8", newline="") as f:
                if f.read() != content:
                    edited.append(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    return edited
