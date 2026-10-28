"""The Claude Code runner (styre/claude.py) and the settings reader (styre/settings.py).

No test calls a real model: `fake_claude` stands in for `claude` and the captured
`claude -p --output-format json` results live in tests/fixtures/.
"""
import json
from pathlib import Path

import pytest

from styre import claude, settings
from styre.timeline import Timeline

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def read_event(timeline_path):
    lines = [json.loads(line) for line in timeline_path.read_text(encoding="utf-8").splitlines()]
    return lines[-1]


def test_settings_load_no_file(monkeypatch, tmp_path):
    monkeypatch.setenv("STYRE_CONFIG", str(tmp_path / "absent" / "styre.json"))
    assert settings.load() == {"frontier": {"command": ["claude"], "timeout": 1800}}


def test_settings_load_from_styre_config(monkeypatch, tmp_path):
    p = tmp_path / "styre.json"
    p.write_text(json.dumps({"frontier": {"command": ["claude", "--model", "opus"], "timeout": 900}}),
                 encoding="utf-8")
    monkeypatch.setenv("STYRE_CONFIG", str(p))
    assert settings.load() == {"frontier": {"command": ["claude", "--model", "opus"], "timeout": 900}}


def test_settings_bad_json(monkeypatch, tmp_path):
    p = tmp_path / "styre.json"
    p.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("STYRE_CONFIG", str(p))
    with pytest.raises(settings.SettingsError, match=str(p)):
        settings.load()


def test_settings_bad_command(monkeypatch, tmp_path):
    for bad in [{"frontier": {"command": []}}, {"frontier": {"command": "claude"}},
                {"frontier": {"command": ["claude", 3]}}]:
        p = tmp_path / "styre.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        monkeypatch.setenv("STYRE_CONFIG", str(p))
        with pytest.raises(settings.SettingsError, match=str(p)):
            settings.load()


def fake_call(monkeypatch, tmp_path, fake_path, prompt="the prompt on stdin",
              reply=None, exit_code=None, sleep=None, timeout=None,
              tools=("Read", "Grep", "Glob"), config=None):
    """One claude.call with fake_claude on PATH and the env a test asks for. Returns the
    (result, timeline, log_dir, fake log lines) it can inspect."""
    monkeypatch.setenv("PATH", fake_path)
    if config is not None:
        cfg = tmp_path / "styre.json"
        cfg.write_text(config, encoding="utf-8")
        monkeypatch.setenv("STYRE_CONFIG", str(cfg))
    else:
        monkeypatch.delenv("STYRE_CONFIG", raising=False)
    for var in ("FAKE_CLAUDE_REPLY", "FAKE_CLAUDE_EXIT", "FAKE_CLAUDE_SLEEP"):
        monkeypatch.delenv(var, raising=False)
    if reply is not None:
        monkeypatch.setenv("FAKE_CLAUDE_REPLY", reply)
    if exit_code is not None:
        monkeypatch.setenv("FAKE_CLAUDE_EXIT", str(exit_code))
    if sleep is not None:
        monkeypatch.setenv("FAKE_CLAUDE_SLEEP", str(sleep))
    log_path = str(tmp_path / "fake_claude.log")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", log_path)
    timeline = Timeline(tmp_path / "timeline.jsonl")
    log_dir = tmp_path / "logs"
    result = claude.call("plan", prompt, SCHEMA, tools, cwd=str(tmp_path),
                         timeline=timeline, log_dir=log_dir, timeout=timeout)
    argv_log = [json.loads(line) for line in Path(log_path).read_text(encoding="utf-8").splitlines()]
    return result, timeline, log_dir, argv_log


def test_success_fixture(monkeypatch, tmp_path, fake_claude):
    result, timeline, log_dir, argv_log = fake_call(
        monkeypatch, tmp_path, fake_claude, reply=str(FIXTURES / "claude_read_tools.json"))
    assert result.output == {"function": "add", "line": 1}
    assert result.error is None
    assert result.usage.tokens_in == 4 + 19268 + 5017  # 24289
    assert result.usage.cached_in == 5017
    assert result.usage.cache_write == 19268
    assert result.usage.tokens_out == 301
    assert result.usage.thinking == 63
    assert result.usage.turns == 3
    assert result.usage.cost_usd == 0.16118339999999998
    assert result.seconds >= 0
    event = read_event(tmp_path / "timeline.jsonl")
    assert event["event"] == "model_call"
    assert event["role"] == "plan"
    assert event["model"] == "claude-opus-5-5"
    assert event["ok"] is True
    assert event["error"] is None
    assert event["tokens_in"] == 24289
    assert (log_dir / "plan.1.json").read_text(encoding="utf-8").startswith('{"duration_api_ms"')
    assert (log_dir / "plan.1.err").exists()


def test_no_tools_fixture(monkeypatch, tmp_path, fake_claude):
    result, timeline, log_dir, argv_log = fake_call(
        monkeypatch, tmp_path, fake_claude, reply=str(FIXTURES / "claude_no_tools.json"), tools=())
    assert result.output == {"answer": "ok"}
    assert result.error is None
    assert result.usage.tokens_in == 2 + 5215 + 1079
    assert "--tools" in argv_log[0]["argv"] and "" in argv_log[0]["argv"]
    assert read_event(tmp_path / "timeline.jsonl")["ok"] is True


def test_budget_error_fixture(monkeypatch, tmp_path, fake_claude):
    result, timeline, log_dir, argv_log = fake_call(
        monkeypatch, tmp_path, fake_claude, reply=str(FIXTURES / "claude_error_budget.json"),
        exit_code=1)
    assert result.output is None
    assert "Reached maximum budget" in result.error
    event = read_event(tmp_path / "timeline.jsonl")
    assert event["ok"] is False
    assert "Reached maximum budget" in event["error"]


def test_missing_command(monkeypatch, tmp_path, fake_claude):
    monkeypatch.setenv("STYRE_CONFIG", str(tmp_path / "missing" / "styre.json"))
    (tmp_path / "missing").mkdir()
    (tmp_path / "missing" / "styre.json").write_text(
        json.dumps({"frontier": {"command": ["no-such-claude-anything"]}}), encoding="utf-8")
    monkeypatch.delenv("FAKE_CLAUDE_REPLY", raising=False)
    monkeypatch.delenv("FAKE_CLAUDE_LOG", raising=False)
    timeline = Timeline(tmp_path / "timeline.jsonl")
    result = claude.call("plan", "p", SCHEMA, (), cwd=str(tmp_path),
                         timeline=timeline, log_dir=tmp_path / "logs")
    assert result.error is not None
    assert "no-such-claude-anything" in result.error
    event = read_event(tmp_path / "timeline.jsonl")
    assert event["ok"] is False
    assert event["error"] is not None


def test_non_json_stdout(monkeypatch, tmp_path, fake_claude):
    reply = tmp_path / "notjson.txt"
    reply.write_text("this is not json at all", encoding="utf-8")
    result, timeline, log_dir, argv_log = fake_call(
        monkeypatch, tmp_path, fake_claude, reply=str(reply))
    assert result.error is not None
    assert result.output is None
    assert "not JSON" in result.error
    event = read_event(tmp_path / "timeline.jsonl")
    assert event["ok"] is False
    assert event["error"] is not None
    assert (log_dir / "plan.1.json").read_text(encoding="utf-8") == "this is not json at all\n"


def test_null_structured_output(monkeypatch, tmp_path, fake_claude):
    reply = tmp_path / "null_out.json"
    reply.write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                                 "structured_output": None}), encoding="utf-8")
    result, timeline, log_dir, argv_log = fake_call(
        monkeypatch, tmp_path, fake_claude, reply=str(reply))
    assert result.error is not None
    assert result.output is None
    assert "no structured output" in result.error
    event = read_event(tmp_path / "timeline.jsonl")
    assert event["ok"] is False
    assert event["error"] is not None


def test_nonzero_exit(monkeypatch, tmp_path, fake_claude):
    # A failed process that prints no JSON: the sentence reports the exit code, and the
    # budget fixture (exit 1, is_error true) is the one case where the error is quoted.
    result, timeline, log_dir, argv_log = fake_call(
        monkeypatch, tmp_path, fake_claude, reply=None, exit_code=3)
    assert result.error is not None
    assert "3" in result.error
    assert result.output is None
    event = read_event(tmp_path / "timeline.jsonl")
    assert event["ok"] is False


def test_timeout(monkeypatch, tmp_path, fake_claude):
    monkeypatch.setenv("PATH", fake_claude)
    monkeypatch.setenv("FAKE_CLAUDE_REPLY", str(FIXTURES / "claude_no_tools.json"))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "fake_claude.log"))
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "30")
    monkeypatch.delenv("FAKE_CLAUDE_EXIT", raising=False)
    monkeypatch.delenv("STYRE_CONFIG", raising=False)
    result = claude.call("plan", "p", SCHEMA, (), cwd=str(tmp_path),
                         timeline=Timeline(tmp_path / "timeline.jsonl"),
                         log_dir=tmp_path / "logs", timeout=5)
    assert result.error is not None
    assert "5s" in result.error
    assert result.usage.tokens_in == 0  # no output reached
    event = read_event(tmp_path / "timeline.jsonl")
    assert event["ok"] is False
    assert event["error"] is not None
    assert result.seconds < 20


def test_prompt_on_stdin_not_argv(monkeypatch, tmp_path, fake_claude):
    prompt = "a fairly long prompt " * 40
    result, timeline, log_dir, argv_log = fake_call(
        monkeypatch, tmp_path, fake_claude, prompt=prompt, reply=str(FIXTURES / "claude_no_tools.json"))
    entry = argv_log[0]
    assert entry["stdin"] == prompt
    assert prompt not in " ".join(entry["argv"])
    argv = entry["argv"]
    assert argv == ["-p", "--output-format", "json", "--json-schema", json.dumps(SCHEMA),
                    "--tools", "Read,Grep,Glob", "--no-session-persistence",
                    "--permission-mode", "dontAsk"]
    assert "--json-schema" in argv
    assert json.dumps(SCHEMA) in argv
    assert "--tools" in argv and "Read,Grep,Glob" in argv
    assert "--no-session-persistence" in argv
    assert "--permission-mode" in argv and "dontAsk" in argv


def test_log_number_counts_role_calls(monkeypatch, tmp_path, fake_claude):
    reply = str(FIXTURES / "claude_no_tools.json")
    for _ in range(2):
        fake_call(monkeypatch, tmp_path, fake_claude, reply=reply)
    log_dir = tmp_path / "logs"
    assert sorted(p.name for p in log_dir.iterdir()) == [
        "plan.1.err", "plan.1.json", "plan.2.err", "plan.2.json"]
    events = [json.loads(line)
              for line in (tmp_path / "timeline.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(events) == 2


def test_log_number_counts_per_role(monkeypatch, tmp_path, fake_claude):
    reply = str(FIXTURES / "claude_no_tools.json")
    fake_call(monkeypatch, tmp_path, fake_claude, reply=reply)
    # A different role counts from 1 in its own sequence, even though `plan` already ran.
    monkeypatch.setenv("PATH", fake_claude)
    monkeypatch.setenv("FAKE_CLAUDE_REPLY", reply)
    log_path = str(tmp_path / "fake_claude.log")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", log_path)
    monkeypatch.delenv("FAKE_CLAUDE_SLEEP", raising=False)
    monkeypatch.delenv("STYRE_CONFIG", raising=False)
    monkeypatch.delenv("FAKE_CLAUDE_EXIT", raising=False)
    claude.call("review", "p", SCHEMA, (), cwd=str(tmp_path),
                timeline=Timeline(tmp_path / "timeline.jsonl"), log_dir=tmp_path / "logs")
    assert (tmp_path / "logs" / "review.1.json").exists()


def test_deadline_defaults_to_frontier_timeout(monkeypatch, tmp_path, fake_claude):
    monkeypatch.setenv("PATH", fake_claude)
    cfg = tmp_path / "styre.json"
    cfg.write_text(json.dumps({"frontier": {"command": ["claude"], "timeout": 5}}), encoding="utf-8")
    monkeypatch.setenv("STYRE_CONFIG", str(cfg))
    reply = str(FIXTURES / "claude_no_tools.json")
    monkeypatch.setenv("FAKE_CLAUDE_REPLY", reply)
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "fake_claude.log"))
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "30")
    timeline = Timeline(tmp_path / "timeline.jsonl")
    result = claude.call("plan", "p", SCHEMA, (), cwd=str(tmp_path),
                         timeline=timeline, log_dir=tmp_path / "logs")
    assert "5s" in result.error
    event = read_event(tmp_path / "timeline.jsonl")
    assert event["ok"] is False


def test_second_answer_from_directory(monkeypatch, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "1.json").write_text(json.dumps({"type": "result", "is_error": False,
                                                "structured_output": {"answer": "first"}}), encoding="utf-8")
    (replies / "2.json").write_text(json.dumps({"type": "result", "is_error": False,
                                                "structured_output": {"answer": "second"}}), encoding="utf-8")
    monkeypatch.setenv("PATH", fake_claude)
    monkeypatch.setenv("FAKE_CLAUDE_REPLY", str(replies))
    log_path = str(tmp_path / "fake_claude.log")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", log_path)
    monkeypatch.delenv("FAKE_CLAUDE_SLEEP", raising=False)
    monkeypatch.delenv("STYRE_CONFIG", raising=False)
    monkeypatch.delenv("FAKE_CLAUDE_EXIT", raising=False)
    first = claude.call("plan", "p", SCHEMA, (), cwd=str(tmp_path),
                        timeline=Timeline(tmp_path / "timeline.jsonl"), log_dir=tmp_path / "logs")
    assert first.output == {"answer": "first"}
    second = claude.call("plan", "p", SCHEMA, (), cwd=str(tmp_path),
                         timeline=Timeline(tmp_path / "timeline.jsonl"), log_dir=tmp_path / "logs")
    assert second.output == {"answer": "second"}
