"""What the run's record keeps about a phase the advisor took up (M4 review)."""
from test_m4_patch import PATCH_ADVICE, advisor_env, answer, edit, events


def test_a_patched_phase_keeps_the_fix_rounds_it_used_before_the_patch(styre, repo, tmp_path,
                                                                        fake_claude):
    replies = tmp_path / "replies"
    answer(replies / "1.json", PATCH_ADVICE)
    answer(replies / "2.json", {"summary": "Wrote done.txt."})
    edit(replies, 2, "done.txt", "done\n")
    r = styre("run", "design.md", "--quiet", "--retries", "1", default="ok",
              plan={"phase1.prompt.md": "bad_gate", "phase1.fix1.md": "bad_gate"},
              env_extra=advisor_env(tmp_path, replies))
    assert r.returncode == 0, r.stdout + r.stderr
    ends = [e for e in events(repo, "phase_end") if e["phase"] == 1]
    assert ends[-1]["status"] == "committed"
    assert ends[-1]["rounds"] == 1
