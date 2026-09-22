#!/usr/bin/env python3
"""A test double for `claude -p`, used by touch.py's tests.

Installed on PATH as `claude` by the same fixture that installs the fake `pi`. Reads
$FAKE_CLAUDE_MODE to decide what to do, and prints one JSON object shaped like a real
`claude -p --output-format json` result.

The real invocation is `claude -p ... <prompt>`, one positional string, same as here.

Modes:
  "implement" — writes done.txt, leaves the design alone: the capability-gap case, where
                the design was sound and the local model simply could not do the work.
  "patch"     — also appends a marker line to the backtick-quoted design path in the
                prompt, simulating a design bug found and fixed.
  "fail"      — changes nothing, so the gate stays red: "even Claude can't close this out".
"""
import json
import os
import re
import sys
from pathlib import Path


def main():
    prompt = sys.argv[-1]
    mode = os.environ.get("FAKE_CLAUDE_MODE", "implement")

    if mode == "patch":
        m = re.search(r"`([^`]+\.md)`", prompt)
        if m:
            path = Path(m.group(1))
            path.write_text(path.read_text(encoding="utf-8") + "\n<!-- fake claude patch -->\n",
                            encoding="utf-8")
    if mode != "fail":
        Path("done.txt").write_text("done\n", encoding="utf-8")

    result = {"patch": "The design was missing a pointer; fixed it and implemented the phase.",
              "implement": "The design was fine. Implemented the phase directly.",
              "fail": "I could not get this green."}[mode]
    print(json.dumps({"result": result, "is_error": False, "total_cost_usd": 0.01,
                      "session_id": "fake-claude"}))


if __name__ == "__main__":
    main()
