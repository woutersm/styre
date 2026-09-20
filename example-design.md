# wordfreq: a word frequency CLI

This is a small example design for testing the overnight orchestrator. It should take a few
minutes per phase.

## Context

A Python package named `wordfreq`, managed with uv. Standard library only at runtime. Dev
dependencies are pytest and ruff, in the `dev` dependency group. `uv.lock` is committed.

Layout (src layout, so `uv sync` installs the package into the project environment):

- `src/wordfreq/__init__.py` exports `count_words` and `top_n`
- `src/wordfreq/core.py` holds the counting logic
- `src/wordfreq/__main__.py` is the command line entry point
- `tests/` holds the tests, `tests/fixtures/` holds sample input

## Non-goals

No third-party runtime dependencies. No packaging or publishing. No stemming, stop words, or
language detection.

## Phase 1: Project setup and core counting library

Set up the uv project (Python 3.10 or newer, package `wordfreq`, dev group with pytest and
ruff). Then implement `count_words(text: str) -> dict[str, int]` in `src/wordfreq/core.py`.
A word is a maximal run of letters, digits or apostrophes. Words are lowercased, so "Don't"
and "don't" count together.

Also implement `top_n(counts: dict[str, int], n: int) -> list[tuple[str, int]]`. It sorts by
count descending, then by word ascending, and returns at most `n` items.

### Exit criteria

- `uv sync --locked` succeeds, so `pyproject.toml` and `uv.lock` agree
- `count_words("The cat and the hat")` returns `{"the": 2, "cat": 1, "and": 1, "hat": 1}`
- Counting ignores case, and treats "don't" as a single word
- Punctuation separates words, and `count_words("")` returns `{}`
- `top_n` breaks ties alphabetically, returns at most `n` items, and returns `[]` for `n=0`
- `tests/test_core.py` has at least one test for each behavior above

### Gate

```
uv sync --locked
uv run ruff check .
uv run pytest -q
```

## Phase 2: Command line interface

Add `python -m wordfreq FILE [--top N]`. It reads a UTF-8 text file, or stdin when FILE is
`-`, and prints one `word count` pair per line, most frequent first. The default for `--top`
is 10. If the file does not exist, print an error to stderr and exit with code 2.

Reuse `count_words` and `top_n` from phase 1. Do not reimplement counting in the CLI.
Create a small `tests/fixtures/sample.txt` with at least 20 words and some repeats.

### Exit criteria

- Running the CLI on `tests/fixtures/sample.txt` with `--top 3` prints exactly 3 lines, each `<word> <count>`
- `-` as FILE reads from stdin
- A missing file exits with code 2, writes an error to stderr, and writes nothing to stdout
- `--top 0` prints nothing and exits 0
- The CLI imports and uses `count_words` and `top_n`, with no second copy of the counting logic
- `tests/test_cli.py` runs the CLI through `subprocess` and covers each behavior above

### Gate

```
uv sync --locked
uv run ruff check .
uv run pytest -q
uv run python -c "import subprocess, sys; r = subprocess.run([sys.executable, '-m', 'wordfreq', 'tests/fixtures/sample.txt', '--top', '3'], capture_output=True, text=True); assert r.returncode == 0 and len(r.stdout.splitlines()) == 3, r"
```
