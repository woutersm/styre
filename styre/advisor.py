"""The advisor's call and its checks.

When a phase stalls, the runner asks the advisor (Claude through `claude -p`, read tools
only) for one advice: an action, a reason for the person and a text. `check` judges the
answer, one English sentence per broken rule, and `advise` makes the call with one retry —
the shape of the planner's retry in `styre/cli.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from styre import claude
from styre.design import Phase, parse_phases, validate
from styre.prompts import advisor_prompt

ACTIONS = ("amend", "split", "patch", "stop")
MAX_PATCHES = 2
READ_TOOLS = ["Read", "Grep", "Glob"]


@dataclass
class Stall:
    """The stop the advisor is asked about: which phase, why, and what it can read."""

    n: str            # the phase number, as text
    phase: Phase      # styre.design.Phase
    context: str      # the phase's design excerpt, exactly as its builder prompt has it
    reason: str       # styre's sentence for why the phase stopped
    progress: str = ""
    gate_report: str = ""
    diff_stat: str = ""
    log: str = ""     # the phase's readable log, relative to the repo root


@dataclass
class Advice:
    """The advisor's answer to one stall."""

    action: str       # one of ACTIONS
    reason: str       # one paragraph for the person
    text: str         # amend: text for the builder; split: the new sections;
                      # patch: the diagnosis; stop: may be ""
    phases: list = field(default_factory=list)   # split only: the new phases, parsed


def schema(actions):
    """The JSON schema of the answer: an action from `actions` (in the order given), a
    reason and a text, nothing else."""
    return {"type": "object",
            "properties": {"action": {"type": "string", "enum": list(actions)},
                           "reason": {"type": "string"}, "text": {"type": "string"}},
            "required": ["action", "reason", "text"], "additionalProperties": False}


def split_problems(phase, n, text):
    """One sentence per rule a split of phase `n` into `text` broke; empty when it is good."""
    phases = parse_phases(text)
    if len(phases) not in (2, 3):
        return [f"The split has {len(phases)} phase; it must have 2 or 3."]
    problems = []
    for k, p in enumerate(phases, 1):
        if not p.title.startswith(f"Phase {n}.{k}:"):
            problems.append(f"Split phase {k}'s title must start with 'Phase {n}.{k}:'.")
    problems += validate(phases)
    last = phases[-1]
    if last.gate != phase.gate:
        problems.append("The split's last phase must keep the phase's gate unchanged.")
    if last.criteria != phase.criteria:
        problems.append("The split's last phase must keep the phase's exit criteria unchanged.")
    if last.acceptance != phase.acceptance:
        problems.append("The split's last phase must keep the phase's acceptance tests "
                        "unchanged.")
    for k, p in enumerate(phases[:-1], 1):
        if p.acceptance:
            problems.append(f"Split phase {k} has acceptance tests; only the last phase may, "
                            "and only the original ones.")
    return problems


def check(answer, stall, actions):
    """Judge the call's structured_output: (Advice, []) when good, else (None, problems)."""
    if not isinstance(answer, dict) or answer.get("action") not in actions:
        return None, [f"The advice's action must be one of: {', '.join(actions)}."]
    problems = []
    reason = answer.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        problems.append("The advice has no reason.")
    text = answer.get("text")
    text = text if isinstance(text, str) else ""
    if not text.strip() and answer["action"] in ("amend", "split", "patch"):
        problems.append("The advice's text is empty; amend, split and patch need it.")
    if answer["action"] == "split":
        problems += split_problems(stall.phase, stall.n, text)
    if problems:
        return None, problems
    phases = parse_phases(text) if answer["action"] == "split" else []
    return Advice(action=answer["action"], reason=reason, text=text, phases=phases), []


def advise(stall, actions, *, cwd, timeline, log_dir):
    """One `claude -p` call with one retry: returns (Advice, None) when the advisor is
    agreed, else (None, one sentence). A call error returns its sentence without a retry."""
    prompt = advisor_prompt(stall, actions)
    result = claude.call("advisor", prompt, schema(actions), READ_TOOLS,
                         cwd=cwd, timeline=timeline, log_dir=log_dir)
    if result.error is not None:
        return None, result.error
    advice, problems = check(result.output, stall, actions)
    if advice is not None:
        return advice, None
    retry = claude.call("advisor", prompt + "\n\nYour advice was refused:\n" +
                        "\n".join(problems), schema(actions), READ_TOOLS,
                        cwd=cwd, timeline=timeline, log_dir=log_dir)
    if retry.error is not None:
        return None, retry.error
    advice, problems = check(retry.output, stall, actions)
    if advice is not None:
        return advice, None
    return None, problems[0]
