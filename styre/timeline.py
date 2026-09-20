"""`<run>/timeline.jsonl`: one JSON object per line, appended and flushed as things happen.

This is the spine a later `styre summarize` reads. Everything in it is measured by the
orchestrator — wall-clock times, return codes, the commit sha — never taken from the agent's
own account of what it did. It is written line by line and flushed so a run that is killed
still leaves a usable record of everything up to the kill.

A Timeline with no path discards its events, so code that takes one does not have to care
whether a run directory exists.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime


class Timeline:
    """Appends timestamped events to one file."""

    def __init__(self, path=None):
        self.path = path

    def event(self, kind, **fields):
        """Append one event. Returns the record, so a caller can log and inspect in one step."""
        record = {"ts": datetime.now().astimezone().isoformat(), "event": kind, **fields}
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        return record

    @contextmanager
    def span(self, kind, **fields):
        """Emit `<kind>_start` now and `<kind>_end` with a duration when the block ends.

        The dict yielded is merged into the end event, which is how a caller reports the
        return code it only learns at the end. The end event is written even when the block
        raises, so a crash mid-gate still leaves the pair on disk.
        """
        self.event(f"{kind}_start", **fields)
        started = time.monotonic()
        result = {}
        try:
            yield result
        finally:
            self.event(f"{kind}_end",
                       **{**fields, "seconds": round(time.monotonic() - started, 1), **result})
