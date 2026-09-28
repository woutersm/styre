"""styre's pi extensions (styre/pi_extensions/), run in Node on their own.

End to end they were verified against real pi through a scripted model server (2026-09-28): a
500-line `bash` came back as 150 lines and a note, a 1,000-line `read` as 300 and the offset to
continue from, and with no-compaction.js a threshold compaction sent no summary request and
ended `aborted` where without it pi sent three that failed. These tests pin the cap's edges.
"""
import json
import shutil
import subprocess

import pytest

from styre.config import PI_EXTENSIONS

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
EXT = {p.name: p for p in PI_EXTENSIONS}


def run_js(tmp_path, name, body):
    """Import one extension as an ES module (copied to .mjs so Node does not guess) and run body."""
    module = tmp_path / (name.replace(".js", ".mjs"))
    module.write_text(EXT[name].read_text(encoding="utf-8"), encoding="utf-8")
    script = f"import * as ext from {json.dumps(module.as_uri())};\n{body}"
    out = subprocess.run(["node", "--input-type=module", "-e", script],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def lines(n):
    return "".join(f"line {i}\n" for i in range(1, n + 1))


def test_a_short_read_and_a_short_command_pass_untouched(tmp_path):
    got = run_js(tmp_path, "cap-output.js", f"""
      console.log(JSON.stringify([ext.capRead({json.dumps(lines(300))}, {{}}),
                                  ext.capBash({json.dumps(lines(150))})]));""")
    assert got == [None, None]


def test_a_long_read_keeps_300_lines_and_says_where_to_continue(tmp_path):
    [text] = run_js(tmp_path, "cap-output.js", f"""
      console.log(JSON.stringify([ext.capRead({json.dumps(lines(1000))}, {{offset: 41}})]));""")
    body, note = text.rsplit("\n", 1)
    assert body.split("\n") == [f"line {i}" for i in range(1, 301)]
    assert note == ("[styre: showing lines 41-340 of the 1000 this read returned. "
                    "Continue with offset=341 and a limit, or grep for the lines you need.]")


def test_a_read_with_a_limit_is_only_cut_by_size(tmp_path):
    many = lines(500)
    [kept, huge] = run_js(tmp_path, "cap-output.js", f"""
      console.log(JSON.stringify([ext.capRead({json.dumps(many)}, {{limit: 500}}),
                                  ext.capRead({json.dumps("x" * 20000)}, {{limit: 10}})]))""")
    assert kept is None  # the agent asked for exactly this range
    assert huge.startswith("x" * 16000) and "cut at 16000 characters of 20000" in huge


def test_a_long_command_keeps_its_head_and_its_tail(tmp_path):
    [text] = run_js(tmp_path, "cap-output.js", f"""
      console.log(JSON.stringify([ext.capBash({json.dumps(lines(500))})]));""")
    out = text.split("\n")
    assert out[:60] == [f"line {i}" for i in range(1, 61)]
    assert out[60] == "[styre: 350 lines omitted of 500. Narrow the command with grep, head or tail.]"
    assert out[61:] == [f"line {i}" for i in range(411, 501)]  # a test run's verdict is at the end


def test_no_compaction_cancels_every_compaction(tmp_path):
    got = run_js(tmp_path, "no-compaction.js", """
      const handlers = {};
      ext.default({on: (name, fn) => { handlers[name] = fn; }});
      const verdict = handlers.session_before_compact({reason: "threshold"});
      console.log(JSON.stringify([Object.keys(handlers), verdict]));""")
    assert got == [["session_before_compact"], {"cancel": True}]
