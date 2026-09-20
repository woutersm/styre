from styre.agents import AGENTS_BODY, write_agents_file
from styre.config import BEGIN, END


def test_writes_a_fresh_file(tmp_path):
    p = tmp_path / "AGENTS.md"
    assert write_agents_file(p) is True  # True means "the project had none"
    text = p.read_text(encoding="utf-8")
    assert text.startswith(BEGIN) and END in text
    assert "unmet_criteria" in text
    assert "write them first" in text  # the listed tests precede the implementation


def test_existing_text_is_kept_and_the_block_appended(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text("# House rules\n\nUse tabs.\n", encoding="utf-8")
    assert write_agents_file(p) is False
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# House rules")
    assert text.count(BEGIN) == 1


def test_only_the_block_is_replaced_on_refresh(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text(f"before\n\n{BEGIN}\nstale\n{END}\n\nafter\n", encoding="utf-8")
    write_agents_file(p)
    text = p.read_text(encoding="utf-8")
    assert "stale" not in text
    assert text.startswith("before") and text.rstrip().endswith("after")
    assert text.count(BEGIN) == 1 and text.count(END) == 1


def test_refresh_is_idempotent(tmp_path):
    p = tmp_path / "AGENTS.md"
    write_agents_file(p)
    first = p.read_text(encoding="utf-8")
    write_agents_file(p)
    assert p.read_text(encoding="utf-8") == first == AGENTS_BODY
