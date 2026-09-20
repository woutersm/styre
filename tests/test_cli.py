import pytest

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


def test_defaults_match_the_documented_ones():
    args = build_parser().parse_args(["run", "d.md"])
    assert (args.retries, args.timeout, args.gate_timeout) == (2, 5400, 900)
    assert args.from_phase == 1 and args.branch is None
    assert not (args.quiet or args.allow_dirty or args.allow_test_changes or args.reset_branch)
