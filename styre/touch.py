"""Claude as the escape hatch — see CLAUDE.md, "The supervising layer".

Invoked only at a phase boundary `run_phase()` already stops at on its own: `BLOCKED`, a
timeout, or the gate still red after `--retries`. One turn per phase, ever; the bounding
lives in `runner._escalate()`, beside the rest of the phase loop it extends.

Nothing here trusts Claude's own account of what it did, the same rule `verify()` already
enforces on pi. Whether the design was patched is judged by the file's *content* changing,
not by what the answer claims, and the code is judged by the same `verify()` pi's diff is —
the gate does not care who wrote it.
"""
from __future__ import annotations

import json
from pathlib import Path

from styre.config import CLAUDE
from styre.gitops import commit, has_staged_changes, head_sha, stage, stage_all, unstage_all
from styre.guard import verify
from styre.process import run as run_command
from styre.review import describe_review


def run_claude(prompt, timeout=None, log=None):
    """One `claude -p` call. Returns a dict with at least `result`, `is_error`, `cost`.

    A missing `claude` binary, a non-zero exit, or unparseable output all come back as
    `is_error: True` rather than raising — a touch that cannot even start is a stop for the
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


def touch_prompt(ctx, n, why):
    """Everything needed to take over one stuck phase, and nothing it has to guess at."""
    return (
        f"Phase {n} of the design at `{ctx.design_path}` stopped: {why}\n\n"
        f"A local model has already had this phase and its fix rounds, and could not get the "
        f"gate green. Read the phase's own prompt ({ctx.run.prompt(n)}) and its transcript "
        f"({ctx.run.log(n)}) to see what it actually tried.\n\n"
        f"Here is what already exists in this repository that this phase's own prose names:\n\n"
        f"{describe_review([ctx.phase(n)])}\n\n"
        f"<design>\n{ctx.context(n)}\n</design>\n\n"
        "Do two things, in this order.\n\n"
        f"1. If the phase stopped because the design itself is wrong — an instruction that "
        f"contradicts something already in the repository, a real ambiguity, a missing "
        f"pointer — fix `{ctx.design_path}` so the phase is achievable as written. Leave the "
        f"edit in the working tree; it is committed separately, by the orchestrator, not by "
        f"you. If the design is sound and the local model simply could not do the work, "
        f"change nothing there.\n"
        "2. Implement the phase yourself, and run the gate until it passes.\n\n"
        "Then stop. The orchestrator runs the gate again and commits; you never run git."
    )


def touch(ctx, n, why_stopped):
    """Claude's one turn at a stuck phase: patch the design if it is wrong, write the phase,
    and be held to the same gate. Returns the reason it stopped, or None if it committed."""
    phase = ctx.phase(n)
    design = Path(ctx.design_path)
    before = design.read_text(encoding="utf-8")
    log = ctx.run.log(n)

    with ctx.tl.span("touch", phase=n) as end:
        result = run_claude(touch_prompt(ctx, n, why_stopped), timeout=ctx.opts.timeout or None,
                            log=log)
        end["is_error"] = result["is_error"]
        end["cost"] = result["cost"]
    patched = design.read_text(encoding="utf-8") != before
    ctx.tl.event("touch_result", phase=n, patched=patched, is_error=result["is_error"],
                 cost=result["cost"], session_id=result["session_id"])
    if result["is_error"]:
        return f"the Claude touch failed to run: {result['result'][:300]}"

    if patched:
        # A plan change and a code change are different kinds of change, so the design fix
        # is its own commit rather than being swept into the phase's by stage_all() below.
        # The index is emptied first: a phase that stopped on the test guard left everything
        # staged, and that must not ride along with the design fix.
        unstage_all()
        stage(ctx.design_path)
        if has_staged_changes():
            commit(f"Touch: design fix for phase {n}")
            sha = head_sha()
            ctx.tl.event("commit", phase=n, sha=sha, subject="Touch design fix", touch=True)
            print(f"    ✓ committed {sha[:7]}  Touch: design fix for phase {n}", flush=True)
        ctx.reload()  # every later phase gets the fixed design, not the one that failed
        phase = ctx.phase(n)

    failure = verify(phase, log, gate_timeout=ctx.opts.gate_timeout, acceptance=ctx.acceptance(n),
                     allow_test_changes=ctx.opts.allow_test_changes, timeline=ctx.tl,
                     phase_n=n, step="touch")
    if failure:
        return f"Claude wrote the phase but the gate is still red: {failure[0]}"

    stage_all()
    if not has_staged_changes():
        return "the Claude touch's gate passed but changed nothing (no staged diff)"
    commit(f"{phase.title}\n\nEscalated: the local model could not pass the gate after its "
           f"own retries; Claude wrote this phase directly, and it passed the same gate "
           f"every phase is held to.")
    sha = head_sha()
    ctx.tl.event("commit", phase=n, sha=sha, subject=phase.title, escalated=True)
    print(f"    ✓ committed {sha[:7]}  {phase.title} (escalated)", flush=True)
    return None
