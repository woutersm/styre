#!/usr/bin/env python3
"""A test double for `claude -p --output-format json`.

Reads the whole prompt from stdin, prints the JSON object the file named by
$FAKE_CLAUDE_REPLY contains (nothing when the variable is unset), then appends its argv
and its stdin as one JSON line to $FAKE_CLAUDE_LOG and exits with $FAKE_CLAUDE_EXIT
(default 0). It sleeps $FAKE_CLAUDE_SLEEP seconds before replying, for the timeout test.

When $FAKE_CLAUDE_REPLY names a directory instead of a file, the call numbered k — counted
through the lines already in $FAKE_CLAUDE_LOG, before its own line is appended — prints
<dir>/<k>.json, so a test can hand a role a first and a second answer.
"""
import json
import os
import sys
import time
from pathlib import Path


def main():
    stdin = sys.stdin.read()
    log_path = os.environ.get("FAKE_CLAUDE_LOG")
    k = 0
    if log_path:
        p = Path(log_path)
        if p.exists():
            k = sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
    target = None
    reply = os.environ.get("FAKE_CLAUDE_REPLY")
    if reply:
        path = Path(reply)
        if path.is_dir():
            path = path / f"{k + 1}.json"
        if path.exists():
            target = path
    sleep = os.environ.get("FAKE_CLAUDE_SLEEP")
    if sleep:
        time.sleep(float(sleep))
    if target is not None:
        sys.stdout.write(target.read_text(encoding="utf-8") + "\n")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"argv": sys.argv[1:], "stdin": stdin}) + "\n")
    sys.exit(int(os.environ.get("FAKE_CLAUDE_EXIT", "0")))


if __name__ == "__main__":
    main()
