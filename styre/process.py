"""Running child processes, and rendering pi's JSON event stream.

Two runners live here. `run()` is for gate commands and git: buffered, one result at the
end. `stream_pi()` is for the agent itself: it reads line by line so a long run can be
watched, and stamps every line with our own arrival time because pi's events carry no
timestamps of their own.
"""
import json
import os
import shlex
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime

GREY, RESET = ("\033[90m", "\033[0m") if sys.stdout.isatty() and not os.environ.get("NO_COLOR") else ("", "")

# A child in its own process group can be taken down as a tree when it times out.
_NEW_GROUP = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
              else {"start_new_session": True})


def kill_tree(p):
    """Kill a process and everything it spawned. A timed-out pi leaves its tool children behind
    otherwise, and they hold ports and locks the next phase needs."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        return
    import signal
    try:
        gid = os.getpgid(p.pid)
    except ProcessLookupError:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(gid, sig)
        except ProcessLookupError:
            return
        try:
            p.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            continue


def show(text, end=""):
    """Write inside the grey span opened by stream_pi, so the codes are not repeated per delta."""
    sys.stdout.write(text + end)
    sys.stdout.flush()


def render_event(d, state):
    """Return the readable part of one pi JSON event, or "". Thinking is deliberately dropped:
    it is the bulk of the stream and the least informative about what the agent actually did.
    The raw stream is kept in the events file, so nothing is lost by condensing here."""
    kind = d.get("type")
    if kind == "message_update":
        e = d.get("assistantMessageEvent") or {}
        et = e.get("type")
        if et == "text_delta":
            delta = e.get("delta") or ""
            if not state.get("in_text"):
                if not delta.strip():
                    return ""  # leading blank deltas, nothing to show yet
                state["in_text"] = True
                return "\n    " + delta.replace("\n", "\n    ")
            return delta.replace("\n", "\n    ")
        if et == "text_end":
            state["in_text"] = False
        elif et == "toolcall_start":
            state["in_text"] = False
            return f"\n    ⚙ {e.get('toolName')} "
    elif kind == "tool_execution_start":
        args = d.get("args") or {}
        first = next(iter(args.values()), "") if isinstance(args, dict) else ""
        return str(first).replace("\n", " ")[:100]
    elif kind == "tool_execution_end":
        return " [error]" if d.get("isError") else " ✓"
    elif kind == "agent_end":
        state["in_text"] = False
        return "\n"
    return ""


def append_log(log, cmd, out, rc):
    """Append one command's readable output to a log file."""
    if not log:
        return
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n$ {cmd if isinstance(cmd, str) else shlex.join(cmd)}\n{out}\n[exit {rc}]\n")


def stream_pi(cmd, timeout=None, log=None, events=None, quiet=False):
    """Run pi, writing every output line to the events file with our own timestamp as it
    arrives, and rendering the non-thinking parts to the terminal. Returns (rc, output tail)."""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", bufsize=1, **_NEW_GROUP)
    except FileNotFoundError as e:
        return 127, f"[styre] command not found: {e}"

    # The log gets the readable transcript; the raw JSON lives in the events file only.
    tail, state = deque(maxlen=100_000), {}
    ev = open(events, "a", encoding="utf-8") if events else None
    # A watchdog rather than a deadline checked in the read loop: the failure that stalls a
    # whole night is a pi that stops printing, and that loop would simply block forever.
    timed_out = threading.Event()
    watchdog = None
    if timeout:
        watchdog = threading.Timer(timeout, lambda: (timed_out.set(), kill_tree(p)))
        watchdog.daemon = True
        watchdog.start()
    if not quiet:
        show(GREY)
    try:
        for line in p.stdout:
            line = line.rstrip("\n")
            if ev:
                ev.write(json.dumps({"ts": datetime.now().astimezone().isoformat(), "line": line}) + "\n")
                ev.flush()
            try:
                text = render_event(json.loads(line), state)
            except (json.JSONDecodeError, TypeError):
                # not a JSON event: text mode, or pi complaining. Keep it rather than
                # swallowing it, otherwise a misconfigured invocation looks like a hang.
                text = "\n    " + line.replace("\n", "\n    ") if line.strip() else ""
            if text:
                tail.append(text)
                if not quiet:
                    show(text)
    finally:
        if watchdog:
            watchdog.cancel()
        if ev:
            ev.close()
        if not quiet:
            show(RESET + "\n")
    try:
        p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        kill_tree(p)
    if timed_out.is_set():
        tail.append("\n[styre] TIMEOUT")
        rc = 124
    else:
        rc = p.returncode if p.returncode is not None else 124
    out = "".join(tail)
    append_log(log, cmd, out, rc)
    return rc, out


def run(cmd, timeout=None, log=None, shell=False):
    """Run a command, append its output to a log file, return (returncode, output).

    The child gets its own process group so a timeout can take down the whole tree.
    """
    try:
        p = subprocess.Popen(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", **_NEW_GROUP)
    except FileNotFoundError as e:
        out, rc = f"[styre] command not found: {e}", 127
    else:
        try:
            out, rc = p.communicate(timeout=timeout)[0] or "", p.returncode
        except subprocess.TimeoutExpired:
            kill_tree(p)
            out, rc = (p.communicate()[0] or "") + "\n[styre] TIMEOUT", 124
    append_log(log, cmd, out, rc)
    return rc, out
