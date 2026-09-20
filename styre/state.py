"""The agent's machine-readable result: .styre/phaseN.state.json.

The agent's own account of its work is never the arbiter, but a missing, mangled or
self-contradictory state file is still a phase failure — `DONE` alongside a non-empty
`unmet_criteria` most of all.
"""
import json


def read_state(path):
    """Read a phase's state file. Returns None if missing or unparseable, so a mangled file is
    a phase failure rather than a crash."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return state if isinstance(state, dict) else None


def state_problem(state):
    """Return a reason the phase should not be accepted, or None."""
    if state is None:
        return "no state file written, or it was not valid JSON"
    status = str(state.get("status", "")).upper()
    if status == "BLOCKED":
        return f"BLOCKED: {state.get('reason') or 'no reason given'}"
    if status != "DONE":
        return f"unexpected status {state.get('status')!r}"
    unmet = state.get("unmet_criteria")
    if not isinstance(unmet, list):
        return "state file has no unmet_criteria list"
    if unmet:
        return "reported DONE but listed unmet criteria: " + "; ".join(str(u) for u in unmet)
    return None
