"""Acceptance tests: written by the design's author, hidden from the agent, run by the gate.

Every other test in a phase is written by the agent that writes the code, so a green gate
proves the agent agrees with itself. SpecBench measured what that is worth: 97% on visible
tests against 0% on held-out ones, for a hard-coded lookup table. An acceptance test is the
design author's own statement of what "done" means, and the agent never sees it:

- It lives in the design, in an optional `### Acceptance` section per phase. The section is
  cut out of the phase before anything else reads it, so it reaches no prompt.
- The gate writes its files into the tree, runs its command, and deletes them again, before
  anything is staged. They are never committed and never there while the agent works.
- A phase's gate runs the acceptance tests of every phase up to and including it, so a later
  phase that breaks an earlier feature is caught.
- A failure's output goes into the fix prompt like any gate failure: the agent learns what
  broke, which it needs to fix it, but never had the test to aim at.
- They are read once, when the run starts. A Claude touch may patch the design; it cannot
  weaken the tests it is then held to.

The format — a fenced block whose info string names a path is a test file, a fenced block
without one is the command, `{files}` in it the paths of that phase's files:

    ### Acceptance
    ```python tests/test_acceptance_calendar.py
    def test_a_weekly_event_is_one_row_per_week(): ...
    ```
    ```
    uv run pytest -q {files}
    ```
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SECTION_RE = re.compile(r"(?ms)^###\s+Acceptance\s*$(.*?)(?=^###\s|\Z)")
BLOCK_RE = re.compile(r"```([^\n`]*)\n(.*?)```", re.S)


@dataclass
class Acceptance:
    """One phase's acceptance tests: its files as (path, text), and the commands that run them."""

    files: list = field(default_factory=list)
    commands: list = field(default_factory=list)


def split(body):
    """(body without its Acceptance section, the Acceptance or None)."""
    m = SECTION_RE.search(body)
    if not m:
        return body, None
    acceptance = Acceptance()
    for info, text in BLOCK_RE.findall(m.group(1)):
        words = info.split()
        if len(words) >= 2:
            acceptance.files.append((words[1], text))
        else:
            acceptance.commands += [ln.strip() for ln in text.splitlines()
                                    if ln.strip() and not ln.strip().startswith("#")]
    return (body[:m.start()] + body[m.end():]).strip(), acceptance


def problems(n, acceptance):
    """What makes phase n's acceptance section unrunnable."""
    if acceptance is None:
        return []
    out = []
    if not acceptance.files:
        out.append(f"Phase {n}'s Acceptance section has no test file: a fenced block whose "
                   "info string names its path, as in ```python tests/test_x.py")
    if not acceptance.commands:
        out.append(f"Phase {n}'s Acceptance section has no command: a fenced block with no "
                   "path, such as `uv run pytest -q {files}`")
    for path, text in acceptance.files:
        p = PurePosixPath(path)
        if p.is_absolute() or ".." in p.parts:
            out.append(f"Phase {n}'s acceptance file `{path}` must be a path inside the repo")
        elif path.endswith(".py"):
            try:
                compile(text, path, "exec")
            except SyntaxError as e:
                out.append(f"Phase {n}'s acceptance file `{path}` does not parse: {e.msg} "
                           f"(line {e.lineno})")
    return out


def run_all(suites, runner, log, timeout=None):
    """Run each (phase n, Acceptance) in turn: write its files, run its commands, delete the
    files. Returns [(label, rc, output)] for every command, in order.

    A path the tree already holds is not overwritten — that would destroy the agent's work —
    and counts as a failure the fix round is told about."""
    results = []
    for n, acceptance in suites:
        written = []
        try:
            taken = [path for path, _ in acceptance.files if Path(path).exists()]
            if taken:
                results.append((f"acceptance (phase {n})", 1,
                                "The acceptance test path(s) " + ", ".join(taken) + " already "
                                "exist in the tree. They belong to the orchestrator: remove "
                                "or rename the file(s) there."))
                continue
            for path, text in acceptance.files:
                target = Path(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
                written.append(target)
            files = " ".join(shlex.quote(path) for path, _ in acceptance.files)
            for command in acceptance.commands:
                cmd = command.replace("{files}", files)
                rc, out = runner(cmd, shell=True, log=log, timeout=timeout)
                results.append((f"acceptance (phase {n}): {cmd}", rc, out))
        finally:
            for target in written:
                target.unlink(missing_ok=True)
    return results
