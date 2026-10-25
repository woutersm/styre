from pathlib import Path

import pytest

from styre import __version__
from styre.cli import build_parser, main


def test_check_prints_the_phases_and_exits_zero(capsys, tmp_path, monkeypatch):
    d = tmp_path / "d.md"
    d.write_text("## Phase 1: X\n\n### Exit criteria\n- a\n\n### Gate\n```\ntrue\n```\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["check", str(d)]) == 0
    assert "Design looks runnable" in capsys.readouterr().out


def test_check_reports_problems_and_exits_one(capsys, tmp_path):
    d = tmp_path / "d.md"
    d.write_text("## Phase 1: X\nbody\n", encoding="utf-8")
    assert main(["check", str(d)]) == 1
    assert "no '### Exit criteria' list" in capsys.readouterr().out


def test_a_design_without_phases_is_an_error(tmp_path):
    d = tmp_path / "d.md"
    d.write_text("just prose\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main(["check", str(d)])
    assert "No '## Phase N" in str(e.value)


def test_a_missing_design_file_is_an_error():
    with pytest.raises(SystemExit) as e:
        main(["check", "/nonexistent/design.md"])
    assert "Could not read the design file" in str(e.value)


def test_run_refuses_an_invalid_design(tmp_path):
    d = tmp_path / "d.md"
    d.write_text("## Phase 1: X\nbody\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main(["run", str(d)])
    assert "Fix the design first" in str(e.value)


def test_run_refuses_an_out_of_range_from_phase(tmp_path):
    d = tmp_path / "d.md"
    d.write_text("## Phase 1: X\n\n### Exit criteria\n- a\n\n### Gate\n```\ntrue\n```\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main(["run", str(d), "--from-phase", "4"])
    assert "between 1 and 1" in str(e.value)


def test_no_command_prints_help(capsys):
    assert main([]) == 2
    assert "usage: styre" in capsys.readouterr().out


def test_the_version_is_reported_and_has_one_source(capsys):
    with pytest.raises(SystemExit) as e:
        build_parser().parse_args(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out.strip() == f"styre {__version__}"
    # pyproject reads the version from the package, so there is nothing here to disagree.
    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert 'version = {attr = "styre.__version__"}' in pyproject


def test_summarize_takes_an_optional_run():
    assert build_parser().parse_args(["summarize"]).run is None
    assert build_parser().parse_args(["summarize", "20260920-1200"]).run == "20260920-1200"


def test_summarize_compare_takes_two_runs():
    args = build_parser().parse_args(["summarize", "--compare", "a", "b"])
    assert args.run is None and args.compare == ["a", "b"]


def test_summarize_refuses_a_run_together_with_compare():
    import pytest
    with pytest.raises(SystemExit) as e:
        main(["summarize", "somerun", "--compare", "a", "b"])
    assert str(e.value) == "Give either a run or --compare A B, not both."


def test_summarize_compare_exits_on_an_unknown_run(tmp_path, monkeypatch):
    import pytest

    import styre.rundir as rd
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rd, "RUNS", tmp_path / "runs")
    (tmp_path / "runs").mkdir()
    with pytest.raises(SystemExit) as e:
        main(["summarize", "--compare", "nope", "b"])
    assert str(e.value) == "No such run: nope."


def test_defaults_match_the_documented_ones():
    args = build_parser().parse_args(["run", "d.md"])
    assert (args.retries, args.timeout, args.gate_timeout) == (2, 7200, 900)
    assert args.from_phase == 1 and args.branch is None
    assert not (args.quiet or args.allow_dirty or args.allow_test_changes or args.reset_branch)


def test_design_opens_claude_on_the_design_skill(tmp_path, monkeypatch):
    import styre.cli as cli
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "not_at_root", lambda: None)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda cmd: calls.append(cmd) or type("R", (), {"returncode": 0})())
    assert main(["design", "CSV", "export"]) == 0
    assert calls == [["/bin/claude", "/styre-design CSV export"]]


def test_design_without_claude_is_an_error(monkeypatch):
    import styre.cli as cli
    monkeypatch.setattr(cli, "not_at_root", lambda: None)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="not on PATH"):
        main(["design"])
