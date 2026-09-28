#!/usr/bin/env python3
"""A test double for the pi coding agent.

Installed on PATH as `pi` by the end-to-end tests. It emits a plausible JSON event stream
(modelled on tests/fixtures/), then performs the action the test asked for by writing into
the working tree, exactly where a real agent would.

The action is chosen by the base name of the `@prompt` argument (`phase1.prompt.md`,
`phase2.fix1.md`, ...), looked up in the JSON object in $FAKE_PI_PLAN. Unknown names fall
back to $FAKE_PI_DEFAULT, or "ok".
"""
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

SKIP_MARKER = "@pytest.mark.skip"


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def empty_transcript():
    """What pi prints when the provider returns nothing: a turn that opens, a message_end
    with an all-zero usage block, and a clean exit. Captured from a real refusal on
    2026-09-22, where the model host rejected the prefill for memory."""
    emit({"type": "session", "version": 3, "id": "fake", "timestamp": "2026-09-19T18:00:00.000Z",
          "cwd": os.getcwd()})
    emit({"type": "agent_start"})
    emit({"type": "turn_start"})
    emit({"type": "message_start", "message": {"role": "assistant", "content": []}})
    emit({"type": "message_end", "message": {"role": "assistant", "content": [],
          "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0,
                    "totalTokens": 0, "cost": {"total": 0}}}})
    emit({"type": "turn_end", "toolResults": []})
    emit({"type": "agent_end", "messages": [], "willRetry": False})
    emit({"type": "agent_settled"})


def transcript(text):
    emit({"type": "session", "version": 3, "id": "fake", "timestamp": "2026-09-19T18:00:00.000Z",
          "cwd": os.getcwd()})
    emit({"type": "agent_start"})
    emit({"type": "turn_start"})
    emit({"type": "message_start", "message": {"role": "assistant", "content": []}})
    emit({"type": "message_update", "assistantMessageEvent":
          {"type": "thinking_start", "contentIndex": 0}})
    emit({"type": "message_update", "assistantMessageEvent":
          {"type": "thinking_delta", "contentIndex": 0, "delta": "secret deliberation"}})
    emit({"type": "message_update", "assistantMessageEvent": {"type": "thinking_end", "contentIndex": 0}})
    # Real pi announces the call in the message stream first, then executes it (confirmed in
    # tests/fixtures/pi_toolcall.jsonl); the renderer's elapsed stamp hangs off that event.
    emit({"type": "message_update", "assistantMessageEvent":
          {"type": "toolcall_start", "contentIndex": 0, "toolName": "bash"}})
    emit({"type": "tool_execution_start", "toolCallId": "t1", "toolName": "bash",
          "args": {"command": "ls -la"}})
    time.sleep(0.01)
    emit({"type": "tool_execution_end", "toolCallId": "t1", "toolName": "bash",
          "result": "ok", "isError": False})
    for chunk in text.split(" "):
        emit({"type": "message_update", "assistantMessageEvent":
              {"type": "text_delta", "contentIndex": 1, "delta": chunk + " "}})
    emit({"type": "message_update", "assistantMessageEvent": {"type": "text_end", "contentIndex": 1}})
    emit({"type": "message_end", "message": {"role": "assistant", "timestamp": 1789842291900,
          "content": [{"type": "thinking", "thinking": "secret deliberation"},
                      {"type": "text", "text": text}],
          "usage": {"input": 10, "output": 5, "cacheRead": 0, "cacheWrite": 0,
                    "totalTokens": CONTEXT, "cost": {"input": 0, "output": 0, "total": 0}}}})
    emit({"type": "turn_end", "toolResults": []})
    emit({"type": "agent_end", "messages": [], "willRetry": False})
    emit({"type": "agent_settled"})


# The context size every message_end reports: a test sets FAKE_PI_CONTEXT to put a step above
# or below styre's relay and resume thresholds.
CONTEXT = int(os.environ.get("FAKE_PI_CONTEXT", "15"))


def growing_transcript(context):
    """One turn that ends with the context at `context` tokens, and then a process that keeps
    working — the shape styre stops at the turn boundary. No agent_end ever comes."""
    emit({"type": "session", "version": 3, "id": "fake", "cwd": os.getcwd()})
    emit({"type": "agent_start"})
    emit({"type": "turn_start"})
    emit({"type": "message_start", "message": {"role": "assistant", "content": []}})
    emit({"type": "message_end", "message": {"role": "assistant", "content": [
          {"type": "text", "text": "still going"}],
          "usage": {"input": 10, "output": 5, "cacheRead": 0, "cacheWrite": 0,
                    "totalTokens": context, "cost": {"total": 0}}}})
    emit({"type": "turn_end", "toolResults": []})
    time.sleep(60)


def write_session(session_dir, name):
    """Save a session the way pi does: `<iso>_<uuid>.jsonl` in --session-dir, with --name in
    a session_info line. Verified against pi 0.85.1."""
    if not session_dir:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3] + "Z"
    path = Path(session_dir) / f"{stamp}_{uuid.uuid4()}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "session", "version": 3, "id": "fake"}) + "\n"
                    + json.dumps({"type": "session_info", "name": name}) + "\n",
                    encoding="utf-8")


def flag(name):
    args = sys.argv[1:]
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def write_state(n, status="DONE", reason="", unmet=(), rounds=0):
    Path(".styre").mkdir(exist_ok=True)
    Path(f".styre/phase{n}.state.json").write_text(json.dumps(
        {"phase": n, "status": status, "reason": reason,
         "unmet_criteria": list(unmet), "fix_rounds_self": rounds}), encoding="utf-8")
    Path(".styre/notes-next.md").write_text(f"Notes from phase {n}.\n", encoding="utf-8")


TITLE = ""  # the heading this phase's prompt told us to write, set in main()


def write_decisions(n):
    """Append a decisions section under the heading the prompt told us to write. No later
    phase reads it back — it is committed for humans — but the heading is part of the
    contract, so the double writes the one it was given."""
    Path("docs").mkdir(exist_ok=True)
    with open("docs/decisions.md", "a", encoding="utf-8") as f:
        f.write(f"\n## Phase {n}: {TITLE or 'fake'}\n\nChose the obvious thing.\n")


def act(action, n):
    if action == "empty":
        return  # the transcript already said it all: nothing came back, nothing is written
    if action == "crash":
        sys.exit(3)
    if action == "hang":
        time.sleep(600)
    if action == "nochange":
        write_state(n)  # only .styre, which is excluded: no staged diff
        return
    if action == "blocked":
        write_decisions(n)
        write_state(n, "BLOCKED", "the design does not say which format to use")
        return
    if action == "blocked_then_ok":
        # Simulates a Claude Touch 1 fixing the design: BLOCKED the first time this phase is
        # attempted, "ok" on any retry — a marker file (untouched by clear_inbox) is what
        # tells the two attempts apart, since both write the same prompt file name.
        marker = Path(f".styre/_touched_phase{n}")
        if marker.exists():
            act("ok", n)
            return
        marker.parent.mkdir(exist_ok=True)
        marker.write_text("1", encoding="utf-8")
        write_decisions(n)
        write_state(n, "BLOCKED", "the design does not say which format to use")
        return
    if action == "lying":
        write_decisions(n)
        Path("done.txt").write_text("done\n", encoding="utf-8")
        write_state(n, "DONE", "", ["the second criterion"])
        return
    if action == "bad_gate":
        Path(f"work{n}.py").write_text("value = 1\n", encoding="utf-8")
        write_decisions(n)
        write_state(n)
        return  # no done.txt, so `test -f done.txt` fails
    if action == "skip_test":
        Path("tests").mkdir(exist_ok=True)
        Path("tests/test_fake.py").write_text(
            f"import pytest\n\n{SKIP_MARKER}\ndef test_thing():\n    assert False\n", encoding="utf-8")
        Path("done.txt").write_text("done\n", encoding="utf-8")
        write_decisions(n)
        write_state(n)
        return
    # "ok"
    Path(f"work{n}.py").write_text(f"value = {n}\n", encoding="utf-8")
    Path("done.txt").write_text("done\n", encoding="utf-8")
    write_decisions(n)
    write_state(n)


def main():
    if "--version" in sys.argv[1:]:
        print("0.85.1-fake")  # a probe, not a run: touch nothing in the working tree
        return
    # styre attaches the task first and what to do now last (a fix round: the phase prompt,
    # then the fix prompt), so the action is chosen by the last attached file, as a real
    # agent follows the last instruction.
    attached = [a[1:] for a in sys.argv[1:] if a.startswith("@")]
    prompt = attached[-1] if attached else ""
    name = Path(prompt).name
    global TITLE
    body = "".join(Path(f).read_text(encoding="utf-8") for f in attached if Path(f).exists())
    m = re.search(r'appending a "## Phase \d+: (.*?)" section', body)
    TITLE = m.group(1) if m else ""
    plan = json.loads(os.environ.get("FAKE_PI_PLAN", "{}"))
    action = plan.get(name, os.environ.get("FAKE_PI_DEFAULT", "ok"))
    n = int(re.search(r"phase(\d+)", name).group(1)) if re.search(r"phase(\d+)", name) else 1
    # Record the pi config directory this process was handed, so a test can assert on what
    # the child actually saw rather than on what the parent meant to set.
    sd = flag("--session-dir")
    resumed = flag("--session")
    run_root = Path(sd).parent.parent if sd else Path(resumed).parent.parent.parent if resumed else None
    if run_root:
        (run_root / f"phase{n}.piconfig").write_text(
            os.environ.get("PI_CODING_AGENT_DIR", ""), encoding="utf-8")
        # Every invocation's arguments, in order, so a test can assert on what styre passed.
        with open(run_root / "pi-argv.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(sys.argv[1:]) + "\n")
    if resumed:
        with open(resumed, "a", encoding="utf-8") as f:  # pi appends to a resumed session
            f.write(json.dumps({"type": "session_info", "name": flag("--name")}) + "\n")
    else:
        write_session(sd, flag("--name"))
    Path(".styre").mkdir(exist_ok=True)
    Path(".styre/progress.md").write_text(f"Done: ran {name}\nNow: {action}\n", encoding="utf-8")
    if action == "grow":
        growing_transcript(int(os.environ.get("FAKE_PI_GROW", "900")))
        return
    if action == "grow_done":
        act("ok", n)  # the work and the state file are written; then the context passes the line
        growing_transcript(int(os.environ.get("FAKE_PI_GROW", "900")))
        return
    if action == "empty":
        empty_transcript()
    else:
        transcript(f"Ran {name} with action {action}.")
    act(action, n)


if __name__ == "__main__":
    main()
