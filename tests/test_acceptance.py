"""styre/acceptance.py: writes a phase's acceptance files into the working tree and
returns the paths the builder had edited."""
from styre import acceptance
from styre.design import Phase


def phase_with(*files):
    return Phase(title="Phase 1: First phase", body="body",
                 acceptance=list(files))


def test_write_creates_a_missing_file_and_returns_empty(tmp_path):
    phase = phase_with(("tests/test_accept_a.py", "def test_a():\n    assert True\n"))
    assert acceptance.write(phase, tmp_path) == []
    out = tmp_path / "tests" / "test_accept_a.py"
    with open(out, encoding="utf-8", newline="") as f:
        assert f.read() == "def test_a():\n    assert True\n"


def test_write_returns_the_paths_of_files_it_overwrote(tmp_path):
    a = tmp_path / "test_accept_a.py"
    b = tmp_path / "sub" / "test_accept_b.py"
    a.write_text("def test_a():\n    assert False  # edited\n", encoding="utf-8")
    b.parent.mkdir()
    b.write_text("edited\n", encoding="utf-8")
    phase = phase_with(("test_accept_a.py", "def test_a():\n    assert True\n"),
                       ("sub/test_accept_b.py", "def test_b():\n    pass\n"),
                       ("test_accept_c.py", "new file\n"))
    assert acceptance.write(phase, tmp_path) == ["test_accept_a.py", "sub/test_accept_b.py"]
    with open(a, encoding="utf-8", newline="") as f:
        assert f.read() == "def test_a():\n    assert True\n"
    with open(b, encoding="utf-8", newline="") as f:
        assert f.read() == "def test_b():\n    pass\n"
    assert (tmp_path / "test_accept_c.py").read_text(encoding="utf-8") == "new file\n"


def test_write_returns_empty_for_an_identical_file(tmp_path):
    target = tmp_path / "test_accept_a.py"
    target.write_text("def test_a():\n    assert True\n", encoding="utf-8")
    phase = phase_with(("test_accept_a.py", "def test_a():\n    assert True\n"))
    assert acceptance.write(phase, tmp_path) == []


def test_write_keeps_crlf_content_byte_for_byte(tmp_path):
    content = "a = 1\r\nb = 2\r\n"
    phase = phase_with(("test_accept_crlf.py", content))
    acceptance.write(phase, tmp_path)
    # Rewrite a second time so the file existed first: the CRLF must survive both.
    assert acceptance.write(phase, tmp_path) == []
    assert (tmp_path / "test_accept_crlf.py").read_bytes() == content.encode("utf-8")
