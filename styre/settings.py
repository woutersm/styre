"""`styre.json`: the user's settings for styre, read from `~/.config/styre/styre.json`
or from `$STYRE_CONFIG` when set.

The file is optional: a missing file means the defaults. There is one section, `frontier`,
which names the command that runs the frontier model (Claude Code) and the deadline a call
has before styre kills it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {"frontier": {"command": ["claude"], "timeout": 1800}}


class SettingsError(ValueError):
    """styre.json exists but is not usable; the message names the file."""


def path() -> Path:
    """Where styre.json lives: $STYRE_CONFIG, or the platform config directory."""
    return Path(os.environ.get("STYRE_CONFIG") or Path.home() / ".config" / "styre" / "styre.json")


def load() -> dict:
    """Read styre.json and return every section with every default filled in.

    Raises SettingsError when the file is not JSON, or `frontier.command` is not a
    non-empty list of strings.
    """
    p = path()
    if not p.exists():
        return {"frontier": dict(DEFAULTS["frontier"], command=list(DEFAULTS["frontier"]["command"]))}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SettingsError(f"Settings file {p} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise SettingsError(f"Settings file {p} must hold a JSON object, not {type(data).__name__}.")
    frontier = {"command": list(DEFAULTS["frontier"]["command"]), "timeout": DEFAULTS["frontier"]["timeout"]}
    if "frontier" in data:
        section = data["frontier"]
        if not isinstance(section, dict):
            raise SettingsError(f"Settings file {p} has a `frontier` section that is not an object.")
        if "command" in section:
            command = section["command"]
            if (not isinstance(command, list) or not command
                    or not all(isinstance(c, str) for c in command)):
                raise SettingsError(
                    f"Settings file {p} has a `frontier.command` that is not a non-empty list of strings.")
            frontier["command"] = command
        if "timeout" in section:
            timeout = section["timeout"]
            if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
                raise SettingsError(
                    f"Settings file {p} has a `frontier.timeout` that is not a positive integer.")
            frontier["timeout"] = timeout
    return {"frontier": frontier}
