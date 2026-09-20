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
