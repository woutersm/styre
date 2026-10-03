import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

DESIGN = """# Fake design

Preamble every phase needs.

## Phase 1: First phase
Do the first thing.

### Exit criteria
- done.txt exists

### Gate
```
test -f done.txt
```

## Phase 2: Second phase
Do the second thing.

### Exit criteria
- done.txt still exists

### Gate
```
test -f done.txt
```
"""


@pytest.fixture
def repo(tmp_path):
    """A git repository holding the design and one commit, as the working directory."""
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("start\n", encoding="utf-8")
    (path / "design.md").write_text(DESIGN, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)
    return path


@pytest.fixture
def fake_pi(tmp_path):
    """Put the fake pi on PATH. Returns the PATH to use."""
    bindir = tmp_path / "bin"  # outside the repo, so it does not dirty the tree
    bindir.mkdir()
    exe = bindir / "pi"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{Path(__file__).parent / "fake_pi.py"}" "$@"\n',
                   encoding="utf-8")
    exe.chmod(0o755)
    return f"{bindir}{os.pathsep}{os.environ['PATH']}"


@pytest.fixture
def pi_config(tmp_path):
    """A lean pi config directory, the way preflight insists a real run has one."""
    d = tmp_path / "piconfig"
    d.mkdir()
    (d / "models.json").write_text('{"providers": {}}', encoding="utf-8")
    (d / "settings.json").write_text("{}", encoding="utf-8")
    return d


@pytest.fixture
def styre(repo, fake_pi, pi_config):
    """Run the CLI in the repo with the fake agent on PATH.

    `plan` maps a prompt file name (`phase1.prompt.md`, `phase1.fix1.md`, ...) to one of the
    fake agent's actions; `default` is used for the names it does not mention.
    """
    def call(*args, plan=None, default="ok", path=None, timeout=120,
             background=False, env_extra=None, cwd=None):
        env = dict(os.environ)
        env["STYRE_PI_CONFIG_DIR"] = str(pi_config)
        env["PATH"] = path if path is not None else fake_pi
        env["PYTHONPATH"] = str(ROOT)
        env["NO_COLOR"] = "1"
        env["FAKE_PI_PLAN"] = json.dumps(plan or {})
        env["FAKE_PI_DEFAULT"] = default
        env.update(env_extra or {})
        argv = [sys.executable, "-m", "styre", *args]
        if background:  # for tests that have to look at a run while it is still going
            return subprocess.Popen(argv, cwd=cwd or repo, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
        return subprocess.run(argv, cwd=cwd or repo, env=env,
                              capture_output=True, text=True, timeout=timeout)
    return call


@pytest.fixture
def commits(repo):
    """Returns a callable giving the repo's commit subjects, newest first."""
    def get():
        out = subprocess.run(["git", "log", "--format=%s"], cwd=repo, capture_output=True, text=True)
        return out.stdout.splitlines()
    return get
