"""Cross-referencing a design's phases against what the target repo already has.

`styre check` validates structure: does every phase have criteria and a gate. It cannot tell
you whether a phase's prose names something that already exists somewhere else in the repo,
outside the files that phase claims to touch. A phase that changes an existing default, an
existing class, or an existing shared test fixture without accounting for every other place
that already depends on it is exactly the class of bug that has produced multi-hour timeouts
in practice: the agent correctly discovers the conflict mid-phase and then has no way to know
it is real rather than a misunderstanding, so it keeps re-deriving the same contradiction
instead of stopping.

This module does the mechanical half of catching that class of bug before a run starts: for
every backtick-quoted identifier a phase's prose names, find every place in the target repo's
*tests* that already reference it — scoped to tests deliberately, since a frozen assertion is
exactly what breaks. It does not judge whether a hit is a real conflict — some are brand-new
names with no hits at all, some are false positives, and the actual call needs a reader. It
just makes every hit findable in one pass instead of one grep at a time, by hand, after a run
has already failed.
"""
from __future__ import annotations

import re
import subprocess

from styre.guard import TEST_PATH

# A backtick span that is exactly one dotted identifier (optionally call-shaped, `foo()`).
# Multi-word spans like `pi -p --mode json` simply do not match and are skipped: they are
# prose, not a reference to something that could already exist in the repo.
IDENT_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*(?:\(\))?)`")

# Language primitives have hits everywhere in any repo and carry no "does this already
# exist" signal — excluding them is what keeps the report about the design, not the language.
_BUILTINS = frozenset({
    "None", "True", "False", "self", "cls",
    "str", "int", "float", "bool", "list", "dict", "set", "tuple", "bytes", "object", "type",
})

MAX_SHOWN = 8


def _tokens(text):
    seen, out = set(), []
    for m in IDENT_RE.finditer(text):
        tok = m.group(1).rstrip("()")
        if len(tok) < 3 or tok in seen or tok in _BUILTINS:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def _grep(token, repo_root):
    """Every `path:line:text` in a test-shaped file already referencing `token`,
    git-tracked files only. Scoped to tests deliberately: that is where a frozen
    assertion breaks when a phase changes something it depends on — the shape of every
    real conflict this module has caught so far. Returns [] both when there are no hits
    and when this is not a git repo — a missing signal is not an error here, `styre
    check` already validates the design on its own.
    """
    try:
        proc = subprocess.run(
            ["git", "grep", "-n", "--fixed-strings", "-w", "--", token],
            cwd=repo_root, capture_output=True, text=True)
    except OSError:
        return []
    if proc.returncode not in (0, 1):
        return []
    hits = []
    for line in proc.stdout.splitlines():
        path, _, rest = line.partition(":")
        if TEST_PATH.search(path):
            hits.append(line)
    return hits


def find_references(phases, repo_root="."):
    """{phase_title: {token: [hit_line, ...]}}, tokens with no outside hits omitted."""
    cache = {}
    result = {}
    for phase in phases:
        per_token = {}
        for tok in _tokens(phase.body):
            if tok not in cache:
                cache[tok] = _grep(tok, repo_root)
            if cache[tok]:
                per_token[tok] = cache[tok]
        if per_token:
            result[phase.title] = per_token
    return result


def describe_review(phases, repo_root="."):
    """The `styre review` rendering."""
    refs = find_references(phases, repo_root)
    out = []
    for phase in phases:
        out.append(f"\n{phase.title}")
        per_token = refs.get(phase.title)
        if not per_token:
            out.append("  no existing repo references found")
            continue
        out.append("  existing repo references found — check these before running this phase:")
        for tok, hits in per_token.items():
            out.append(f"    `{tok}` ({len(hits)})")
            for hit in hits[:MAX_SHOWN]:
                out.append(f"      {hit}")
            if len(hits) > MAX_SHOWN:
                out.append(f"      ... and {len(hits) - MAX_SHOWN} more")
    out.append(
        "\nA hit means something in the repo already uses that name — not that the phase is "
        "wrong. Read each one: does this phase's plan account for it?")
    return "\n".join(out)
