"""Claude as reviewer and escape hatch — see CLAUDE.md, "The supervising layer".

Invoked only at a phase boundary `run_phase()` already stops at on its own: `BLOCKED`, a
timeout, or the gate still red after `--retries`. This module holds the two Claude
invocations only; the bounding (at most `MAX_TOUCHES` per phase) and the retry/escalate/stop
control flow stay in `runner.py`, where the rest of the phase loop already lives.

Nothing here trusts Claude's own account of what it did, the same rule `verify()` already
enforces on pi. Touch 1 is judged by whether the design file's *content* changed, not by
what Claude's answer claims. Touch 2's diff is judged by the same `verify()` pi's diff is —
the gate does not care who wrote it.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from styre.config import CLAUDE
from styre.gitops import commit, has_staged_changes, head_sha, stage_all
from styre.guard import verify
from styre.process import run as run_command
from styre.review import describe_review


def run_claude(prompt, timeout=None, log=None):
    """One `claude -p` call. Returns a dict with at least `result`, `is_error`, `cost`.

    A missing `claude` binary, a non-zero exit, or unparseable output all come back as
    `is_error: True` rather than raising — a Touch that cannot even start is a stop for the
    caller to act on, not a crash.
    """
    rc, out = run_command(CLAUDE + [prompt], timeout=timeout, log=log)
    if rc != 0:
        return {"result": out, "is_error": True, "cost": None, "session_id": None}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"result": out, "is_error": True, "cost": None, "session_id": None}
    return {"result": data.get("result", ""), "is_error": bool(data.get("is_error")),
            "cost": data.get("total_cost_usd"), "session_id": data.get("session_id")}


def review_prompt(design_path, n, phase, why, prompt_path, log_path):
    """The Touch 1 prompt: everything needed to judge one stop, nothing it has to guess at."""
    review = describe_review([phase])
    return (
        f"Phase {n} of the design at `{design_path}` just stopped: {why}\n\n"
        f"Read the phase's own prompt ({prompt_path}) and its transcript ({log_path}) to see "
        f"what the local model actually tried. Here is what already exists in this repo that "
        f"this phase's own prose names:\n\n{review}\n\n"
        "Judge: is this a bug in the design (an instruction that contradicts something "
        "already in the repo, a real ambiguity, a missing pointer) or a raw capability gap "
        "(the local model cannot get this right even with a clear design)?\n\n"
        f"If it is a design bug: fix `{design_path}` directly, the same way you would edit "
        "any file, so the phase is achievable as written. Say what you changed and why, in "
        "one or two sentences.\n\n"
        "If it is a capability gap, not a design bug: do not edit the design, and do not "
        "change any other file. Say so plainly — a later step handles that case, not you."
    )


def touch1_review(design_path, n, phase, why, run, tl, timeout=None):
    """Claude reads the stop and judges: design bug, or capability gap?

    Returns True if the design file's content changed (resume the phase with a fresh local
    attempt) or False otherwise (escalate to Touch 2).
    """
    design_file = Path(design_path)
    before = design_file.read_text(encoding="utf-8")
    prompt = review_prompt(design_path, n, phase, why, run.prompt(n), run.log(n))
    log = run.root / "logs" / f"phase{n}.touch1.log"
    with tl.span("touch1", phase=n) as end:
        result = run_claude(prompt, timeout=timeout, log=log)
        end["is_error"] = result["is_error"]
        end["cost"] = result["cost"]
    patched = design_file.read_text(encoding="utf-8") != before
    tl.event("touch1_result", phase=n, patched=patched, is_error=result["is_error"],
             cost=result["cost"], session_id=result["session_id"])
    return patched


def touch2_execute(context, n, phase, opts, run, tl):
    """Claude writes the phase itself; styre verifies and commits it, exactly as it would
    pi's diff. Returns a (why, minutes) pair: `why` is None only on a clean commit."""
    prompt = (
        f"Implement Phase {n} of the design directly. It has already stopped twice with a "
        f"local model attempting it, so you are writing the code yourself this time, not "
        f"reviewing.\n\n{context}\n\n"
        f"Run the gate yourself as you go until it passes, then stop — the orchestrator "
        f"verifies and commits, not you."
    )
    log = run.log(n)
    start = time.time()
    with tl.span("touch2", phase=n) as end:
        result = run_claude(prompt, timeout=opts.timeout or None, log=log)
        end["is_error"] = result["is_error"]
        end["cost"] = result["cost"]

    why = None
    if result["is_error"]:
        why = f"Touch 2 (direct execution) failed to run: {result['result'][:300]}"
    else:
        failure = verify(phase, log, gate_timeout=opts.gate_timeout,
                         allow_test_changes=opts.allow_test_changes, timeline=tl,
                         phase_n=n, step="touch2")
        if failure:
            why = f"Touch 2 wrote code but the gate is still red: {failure[0]}"

    if why is None:
        stage_all()
        if not has_staged_changes():
            why = "Touch 2's gate passed but changed nothing (no staged diff)"
        else:
            commit(f"{phase.title}\n\nEscalated: the local model could not pass the gate "
                  f"after its own retries and a Claude design review; Claude wrote this "
                  f"phase directly, and it passed the same gate every phase is held to.")
            tl.event("commit", phase=n, sha=head_sha(), subject=phase.title, escalated=True)

    return why, round((time.time() - start) / 60, 1)
