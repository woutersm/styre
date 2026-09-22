"""Running child processes, and rendering pi's JSON event stream.

Two runners live here. `run()` is for gate commands and git: buffered, one result at the
end. `stream_pi()` is for the agent itself: it reads line by line so a long run can be
watched, and stamps every line with our own arrival time because pi's events carry no
timestamps of their own.

What reaches a human while a phase runs is deliberately three things: how far into the step
we are, which tool the agent called with what, and whether it worked. The rendering goes to
the terminal and to `<run>/logs/phaseN.log` as it happens, so `tail -f` on the log follows a
phase in flight rather than showing up when the phase is already over.
"""
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime

GREY, RESET = ("\033[90m", "\033[0m") if sys.stdout.isatty() and not os.environ.get("NO_COLOR") else ("", "")

INDENT = " " * len("[+00:00] ")  # continuation lines line up under the elapsed stamp
IDLE_TICK = 5  # how often the watchdog looks; a kill lands within this of the deadline

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


def elapsed(state):
    """`[+MM:SS] ` into the current step, or "" when nothing has started the clock.

    pi stamps almost nothing (see CLAUDE.md's pi reference), so this is our own clock, reset
    per pi process. A fix round starting over at +00:00 is the intended reading: the question
    a watcher has is how long *this* attempt has been going.
    """
    t0 = state.get("t0")
    if t0 is None:
        return ""
    seconds = int(time.monotonic() - t0)
    return f"[+{seconds // 60:02d}:{seconds % 60:02d}] "


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
                return "\n" + elapsed(state) + delta.replace("\n", "\n" + INDENT)
            return delta.replace("\n", "\n" + INDENT)
        if et == "text_end":
            state["in_text"] = False
        elif et == "toolcall_start":
            state["in_text"] = False
            return f"\n{elapsed(state)}⚙ {e.get('toolName')} "
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


def _watch_idle(p, timeout, clock, stop, timed_out):
    """Kill pi once it has gone `timeout` seconds without printing anything.

    Idle, not a deadline: a phase that is working and printing is allowed to take as long as
    it takes, and the failure this guards against — a model host that has gone away or a
    dropped Wi-Fi link, leaving pi blocked on a socket — is exactly a process that stops
    printing. A deadline started once at launch kills productive work instead, which is how
    the two differ in the only case that matters.

    So the timeout has to stay comfortably longer than the longest single tool call the agent
    might make: pi emits nothing between `tool_execution_start` and `tool_execution_end`, so
    from here a 30-minute test suite running inside the phase is indistinguishable from a
    dead link. That is why the default is hours rather than minutes.
    """
    while not stop.wait(min(IDLE_TICK, timeout)):
        if time.monotonic() - clock["last"] >= timeout:
            timed_out.set()
            kill_tree(p)
            return


def stream_pi(cmd, timeout=None, log=None, events=None, quiet=False):
    """Run pi, writing every output line to the events file with our own timestamp as it
    arrives, and the readable rendering to the terminal and the log as it happens.

    Returns the return code. `timeout` is seconds of *silence* allowed, not total runtime.
    """
    lg = open(log, "a", encoding="utf-8") if log else None
    if lg:
        lg.write(f"\n$ {shlex.join(cmd)}\n")
        lg.flush()

    def emit(text):
        """One rendered chunk, to the terminal and through to the log as it happens."""
        if lg:
            lg.write(text)
            lg.flush()
        if not quiet:
            show(text)

    def finish(rc):
        if lg:
            lg.write(f"\n[exit {rc}]\n")
            lg.close()
        return rc

    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", bufsize=1, **_NEW_GROUP)
    except FileNotFoundError as e:
        emit(f"[styre] command not found: {e}")
        return finish(127)

    # The log gets the readable transcript; the raw JSON lives in the events file only.
    state = {"t0": time.monotonic()}
    clock = {"last": time.monotonic()}
    ev = open(events, "a", encoding="utf-8") if events else None
    timed_out, stop = threading.Event(), threading.Event()
    if timeout:
        threading.Thread(target=_watch_idle, args=(p, timeout, clock, stop, timed_out),
                         daemon=True).start()
    if not quiet:
        show(GREY)
    try:
        for line in p.stdout:
            clock["last"] = time.monotonic()
            line = line.rstrip("\n")
            if ev:
                ev.write(json.dumps({"ts": datetime.now().astimezone().isoformat(), "line": line}) + "\n")
                ev.flush()
            try:
                text = render_event(json.loads(line), state)
            except (json.JSONDecodeError, TypeError):
                # not a JSON event: text mode, or pi complaining. Keep it rather than
                # swallowing it, otherwise a misconfigured invocation looks like a hang.
                text = "\n" + INDENT + line.replace("\n", "\n" + INDENT) if line.strip() else ""
            if text:
                emit(text)
    finally:
        stop.set()
        if ev:
            ev.close()
        if not quiet:
            show(RESET + "\n")
    try:
        p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        kill_tree(p)
    if timed_out.is_set():
        emit(f"\n[styre] TIMEOUT: no output for {timeout}s")
        return finish(124)
    return finish(p.returncode if p.returncode is not None else 124)


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
