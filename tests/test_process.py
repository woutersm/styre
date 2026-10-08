"""The child processes styre starts: pi and the gate commands."""
import os
import sys

import pytest

from styre.process import run, stream_pi

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="uses cat")


@pytest.fixture
def open_stdin():
    """A stdin that is neither a terminal nor ever closed, as under a harness or a scheduler."""
    r, w = os.pipe()
    saved = os.dup(0)
    os.dup2(r, 0)
    yield
    os.dup2(saved, 0)
    for fd in (r, w, saved):
        os.close(fd)


def test_a_gate_command_gets_no_stdin(open_stdin):
    assert run("cat", shell=True, timeout=10) == (0, "")


def test_pi_gets_no_stdin(open_stdin, tmp_path):
    """`pi -p` reads a piped stdin to its end before it starts; an open one hung a run."""
    assert stream_pi(["cat"], timeout=10, events=tmp_path / "e.jsonl", quiet=True) == 0
