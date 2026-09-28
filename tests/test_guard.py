from styre import guard


def diff(path, *lines, old=None):
    return f"--- a/{old or path}\n+++ b/{path}\n@@\n" + "\n".join(lines) + "\n"


def test_clean_diff_passes():
    assert guard.test_tampering(diff("tests/test_core.py", "+def test_new():", "+    assert True")) is None


def test_added_skip_marker_is_caught():
    problem = guard.test_tampering(diff("tests/test_core.py", "+@pytest.mark.skip", "+def test_x():"))
    assert "skipped or marked xfail" in problem


def test_xfail_and_js_only_are_caught():
    assert guard.test_tampering(diff("tests/a.py", "+@pytest.mark.xfail")) is not None
    assert guard.test_tampering(diff("src/thing.test.ts", "+  it.only('x', () => {})")) is not None


def test_net_removal_of_tests_is_caught():
    problem = guard.test_tampering(diff("tests/test_core.py", "-def test_a():", "-def test_b():",
                                  "+def test_c():"))
    assert "1 test function(s) were removed" in problem


def test_renaming_a_test_is_not_a_removal():
    assert guard.test_tampering(diff("tests/test_core.py", "-def test_a():", "+def test_b():")) is None


def test_deleted_test_file_is_attributed_to_its_old_path():
    d = "--- a/tests/test_core.py\n+++ /dev/null\n@@\n-def test_a():\n-    assert True\n"
    assert "1 test function(s) were removed" in guard.test_tampering(d)


def test_non_test_files_are_ignored():
    assert guard.test_tampering(diff("src/app.py", "+# pytest.mark.skip", "-def test_helper():")) is None


def test_a_red_gate_runs_every_command_and_reports_every_failure(tmp_path, monkeypatch):
    """One fix round for all of a gate's failures, not one per failure: the commands after a
    red one still run, and the report names each."""
    from types import SimpleNamespace
    monkeypatch.chdir(tmp_path)
    phase = SimpleNamespace(gate=["echo lint-broken; exit 1", "true", "echo tests-broken; exit 2"])
    short, full = guard.verify(phase, tmp_path / "log", allow_test_changes=True)
    assert short == "gate failed: echo lint-broken; exit 1 (+1 more)"
    assert "2 of the 3 gate commands failed" in full
    assert "lint-broken" in full and "tests-broken" in full and "exit code 2" in full


def test_a_green_gate_still_passes(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.chdir(tmp_path)
    assert guard.verify(SimpleNamespace(gate=["true", "true"]), tmp_path / "log",
                        allow_test_changes=True) is None
