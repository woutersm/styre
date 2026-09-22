#!/usr/bin/env python3
"""A test double for `claude -p`, used by touch.py's tests.

Installed on PATH as `claude` by the same fixture that installs the fake `pi`. Reads
$FAKE_CLAUDE_MODE to decide what to do, and prints one JSON object shaped like a real
`claude -p --output-format json` result.

It tells Touch 1 and Touch 2 apart by a phrase each prompt always carries (see touch.py's
`review_prompt` and `touch2_execute`), not by an argument — the real invocation is
`claude -p ... <prompt>`, one positional string, same as here.

Modes:
  "patch"        — Touch 1 finds the backtick-quoted design path in the prompt and appends a
                   marker line to it, simulating a real fix. Touch 2 (if reached) succeeds.
  "decline"      — Touch 1 touches nothing, reports a capability gap. Touch 2 (if reached)
                   succeeds — the default once escalated.
  "decline_fail" — Touch 1 declines; Touch 2 also does not write done.txt, so the gate stays
                   red — the "even Claude can't close this out" case.
"""
import json
import os
import re
import sys
from pathlib import Path

TOUCH1_MARKER = "Judge: is this a bug in the design"
TOUCH2_MARKER = "writing the code yourself"


def main():
    prompt = sys.argv[-1]
    mode = os.environ.get("FAKE_CLAUDE_MODE", "decline")
    result = "noop"

    if TOUCH1_MARKER in prompt:
        if mode == "patch":
            m = re.search(r"`([^`]+\.md)`", prompt)
            if m:
                path = Path(m.group(1))
                path.write_text(path.read_text(encoding="utf-8") + "\n<!-- fake claude patch -->\n",
                                encoding="utf-8")
            result = "Fixed the design: it was missing a pointer."
        else:
            result = "This is a capability gap, not a design bug. No changes made."
    elif TOUCH2_MARKER in prompt:
        if mode != "decline_fail":
            Path("done.txt").write_text("done\n", encoding="utf-8")
        result = "Implemented the phase directly."

    print(json.dumps({"result": result, "is_error": False, "total_cost_usd": 0.01,
                      "session_id": "fake-claude"}))


if __name__ == "__main__":
    main()
