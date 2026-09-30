"""Git operations. The orchestrator owns the history; the agent is told not to touch it."""
from pathlib import Path

from styre.config import EXCLUDES
from styre.process import run


def git(*args):
    """Run a git command, return (returncode, output)."""
    return run(["git", *args])


def in_repo():
    return git("rev-parse", "--git-dir")[0] == 0


def not_at_root():
    """The repository root when the current directory is inside a repository but not at its
    root, else None. styre writes AGENTS.md and .styre/ into the current directory, and the
    agent works relative to it, so a run from a subdirectory scatters both into it."""
    rc, out = git("rev-parse", "--show-toplevel")
    if rc != 0:
        return None
    root = Path(out.strip()).resolve()
    return None if Path.cwd().resolve() == root else root


def is_dirty():
    return bool(git("status", "--porcelain")[1].strip())


def stage_all():
    git("add", "-A")


def stage(path):
    git("add", "--", str(path))


def unstage_all():
    """Empty the index, leaving the working tree alone."""
    git("reset", "-q")


def staged_diff():
    return git("diff", "--cached", "-U0")[1]


def has_staged_changes():
    return git("diff", "--cached", "--quiet")[0] != 0


def commit(message):
    return git("commit", "-q", "-m", message)[0]


def current_branch():
    return git("rev-parse", "--abbrev-ref", "HEAD")[1].strip()


def head_sha():
    return git("rev-parse", "HEAD")[1].strip()


def branch_exists(branch):
    return git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")[0] == 0


def phase_commits(branch):
    """Subjects of the phase commits already on a branch, newest first."""
    return [ln for ln in git("log", "--format=%s", branch)[1].splitlines() if ln.startswith("Phase ")]


def add_excludes():
    """Append the orchestrator's artifacts and caches to the repo's local exclude file."""
    rc, path = git("rev-parse", "--git-path", "info/exclude")
    exclude = Path(path.strip()) if rc == 0 and path.strip() else Path(".git/info/exclude")
    exclude.parent.mkdir(parents=True, exist_ok=True)
    have = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
    with open(exclude, "a", encoding="utf-8") as f:
        f.writelines(p + "\n" for p in EXCLUDES if p not in have)
    return exclude


def work_tree_id():
    """A hash of the working tree as it stands — tracked and untracked files, the excludes
    honoured — or None. Built in a throwaway index, so the real one is never touched. Two
    equal ids mean nothing in the tree changed between them."""
    import os
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        add = subprocess.run(["git", "add", "-A"], env=env, capture_output=True)
        tree = subprocess.run(["git", "write-tree"], env=env, capture_output=True, text=True)
    return tree.stdout.strip() if add.returncode == 0 and tree.returncode == 0 else None
