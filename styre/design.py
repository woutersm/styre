"""Parsing the design document.

Any preamble, then one block per phase:

    ## Phase 1: Title
    What to build.

    ### Exit criteria
    - a statement the agent must make true

    ### Gate
    ```
    uv run pytest -q
    ```

Exit criteria are plain prose for the agent. The gate is what the orchestrator enforces.
A phase with no criteria list or no gate block is a hard error.

A phase's prompt gets `phase_context()` rather than the whole document: the preamble every
phase needs, an index of the phase titles, and its own section. Earlier phases reach it
through the decisions log and the previous phase's notes instead of through their text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PHASE_RE = re.compile(r"(?m)^##\s+(Phase\s+\d+.*?)\s*$")
# A markdown document named anywhere in the design, backticked or bare. Code paths are not
# matched: a phase naming `src/app/dates.py` is naming the file it creates, which is the
# point. A *document* is something the agent will go and read.
DOC_RE = re.compile(r"`?((?:[\w.\-]+/)*[\w.\-]+\.md)`?")
# Files the agent is told to write, or that pi loads on its own. Naming these is correct.
CONTRACT_DOCS = frozenset({"decisions.md", "AGENTS.md", "notes-next.md"})
# Naming a document is fine — a design cross-references other plans all the time. What is
# not fine is *telling the agent to go and read one*, so only a reading verb near the path
# counts. Without this the check reported 7 documents on a real design where 1 mattered,
# which is the failure `review.py` already made once: signal buried in true-but-useless.
READ_RE = re.compile(r"\b(read|consult|refer to|study|look at|open)\b", re.I)
# "Do not open anything in `docs/` — not `agent-design.md`" is a design doing the right
# thing, and warning about it would teach the reader to ignore the warning. A negation just
# before the verb flips the meaning.
NOT_RE = re.compile(r"\b(do not|don't|never|no need to|rather than|instead of|without)\b\W*$",
                    re.I)
READ_WINDOW = 160
NEGATION_WINDOW = 40
MANY_CRITERIA = 8
# A phase gated by two toolchains at once — the gate runs in the root *and* in `cd ui` — is
# a phase that changes a backend and the UI that shows it. Measured over app's 44 phases with
# a design on record (2026-09-29): 6 of the 7 such phases peaked at 74-116k context, past the
# 72k relay line, and the seventh (a UI shell) at 47k. It is said once, naming the phases:
# on app every UI phase is one, and a warning per phase would be read as noise. The heuristic
# this replaced — paths in 2+ top-level areas — flagged 12 phases of which 6 ran large.
FULL_STACK = 2
# A dependency the design names (on a line saying "depend…", or in `uv add`/`npm install`)
# and the repo does not have yet. On app's sources phase 3 the design named `icalendar` and
# gave no example of it, and each of four steps spent ~12 `python -c` calls learning its API.
DEPENDS_RE = re.compile(r"depend", re.I)
INSTALL_RE = re.compile(r"\b(?:uv add|pip install|npm install|npm i|pnpm add|yarn add)\s+([^\n`]+)")
TICKED_RE = re.compile(r"`([@\w][\w./@-]*)`")
# The test guard rejects an added skip or xfail marker, so a design that *asks* for one has
# written a phase that cannot pass its own verification. Measured 2026-09-23: app's phase
# 12 said "skip on non-macOS as `tests/test_scripts.py` already does", the agent did
# exactly that, and the guard rejected the phase — the guard overruling the human, resolved
# only by spending a fix round arguing the markers back out. styre's own suite skips on
# Windows for the same reason, so this is not a rare shape.
# Only the directive forms. A bare "skip" is ordinary English, and on a real design the
# loose version flagged "`rrule`'s skipping behaviour" — the subject under test, not a test
# skip — which is the signal-in-noise failure `review.py` made once with MAX_HITS and
# `doc_references` made with its seven documents. A marker name, "skip" governing a test
# noun, or "skip on/when/unless" governing a condition: nothing else counts.
SKIP_RE = re.compile(r"\b(?:skipif|xfail|xit)\b"
                     r"|\b(?:pytest\.mark\.skip|unittest\.skip)"
                     r"|\bskip(?:ped)?\s+(?:this|these|those|that|the|a|any|it|them|"
                     r"[\w.\-/]*test[\w.\-/]*)\b"
                     r"|\bskip(?:ped)?\s+(?:on|when|unless|if|under|for)\b", re.I)
# Even a directive needs to be about tests: "the poller will skip on a retryable error" is
# not this warning's business.
TEST_WORD_RE = re.compile(r"\b(test|tests|pytest|unittest|suite|spec)\b", re.I)
SKIP_WINDOW = 120
SECTION_RE = re.compile(r"(?m)^###\s+(.+?)\s*$")
FENCE_RE = re.compile(r"```[a-z]*\n(.*?)```", re.S)


@dataclass
class Phase:
    """One '## Phase N: Title' block of the design."""

    title: str
    body: str
    criteria: list[str] = field(default_factory=list)
    gate: list[str] = field(default_factory=list)

    @property
    def short_title(self):
        """The title without the 'Phase N:' prefix, for the decisions-log heading."""
        return self.title.split(":", 1)[-1].strip()


def parse_phases(text):
    """Split a design document into Phase objects, in document order."""
    parts = PHASE_RE.split(text)
    phases = []
    for i in range(1, len(parts), 2):
        title, body = parts[i].strip(), parts[i + 1].strip()
        sections = SECTION_RE.split(body)
        named = {sections[j].strip().lower(): sections[j + 1] for j in range(1, len(sections), 2)}
        criteria = [ln.strip()[2:].strip() for ln in named.get("exit criteria", "").splitlines()
                    if ln.strip().startswith(("- ", "* "))]
        block = FENCE_RE.search(named.get("gate", ""))
        gate = [ln.strip() for ln in (block.group(1) if block else "").splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        phases.append(Phase(title=title, body=body, criteria=criteria, gate=gate))
    return phases


def preamble(text):
    """Everything before the first phase heading: the material every phase needs."""
    m = PHASE_RE.search(text)
    return (text[:m.start()] if m else text).strip()


def phase_context(text, phases, n):
    """The design excerpt for phase `n`'s prompt: preamble, phase index, that phase in full."""
    index = "\n".join(f"- {p.title}" + ("  <- yours" if i == n else "")
                       for i, p in enumerate(phases, 1))
    phase = phases[n - 1]
    return f"{preamble(text)}\n\n## The phases of this design\n\n{index}\n\n## {phase.title}\n\n{phase.body}"


def validate(phases):
    """Return a list of human-readable problems that make the design unrunnable."""
    problems = [f"Phase {i} has no '### Exit criteria' list."
                for i, p in enumerate(phases, 1) if not p.criteria]
    problems += [f"Phase {i} has no '### Gate' code block."
                 for i, p in enumerate(phases, 1) if not p.gate]
    return problems


def doc_references(text, design_path=""):
    """Markdown documents a chunk of design prose names, minus the ones it is meant to.

    A phase that points the agent at a document has an unbounded prompt: the document's
    size is not in the design and nobody sees it until the run is going. On one real design
    a single preamble line — "the design means `docs/agent-design.md`, read it first" —
    turned a 2.3 KB phase into a 44 KB context, the model returned zero tokens, and the
    failure surfaced as "no state file written". `styre check` said the design was runnable
    throughout, because structurally it was.
    """
    own = design_path.replace("\\", "/").split("/")[-1] if design_path else ""
    found, seen = [], set()
    for m in DOC_RE.finditer(text):
        doc = m.group(1)
        name = doc.split("/")[-1]
        if name in CONTRACT_DOCS or name == own or name in seen:
            continue
        lo = max(0, m.start() - READ_WINDOW)
        near = text[lo:m.end() + READ_WINDOW]
        if not any(not NOT_RE.search(near[max(0, r.start() - NEGATION_WINDOW):r.start()])
                   for r in READ_RE.finditer(near)):
            continue  # every reading verb nearby is negated: the design forbids the read
        seen.add(name)
        found.append(doc)
    return found


def skip_requests(text):
    """Excerpts where a phase's prose asks for a skipped or xfailed test.

    The guard is not negotiable and the design is written by a human, so the two
    contradicting each other is the design's bug to fix: the phase will be rejected for
    doing what it was told. Only a skip *near a test word* counts, and a negation just
    before it flips the meaning — "never skip a test" is the design agreeing with the
    guard, and warning about that would teach the reader to ignore the warning.
    """
    for m in SKIP_RE.finditer(text):
        lo = max(0, m.start() - SKIP_WINDOW)
        near = text[lo:m.end() + SKIP_WINDOW]
        if not TEST_WORD_RE.search(near):
            continue
        if NOT_RE.search(text[max(0, m.start() - NEGATION_WINDOW):m.start()]):
            continue
        line = next((ln for ln in text.splitlines() if m.group(0) in ln), m.group(0))
        return " ".join(line.strip().lstrip("-*# ").split())[:160]
    return None


def toolchains(phase):
    """The directories a phase's gate runs in: "." for a plain command, X for `cd X && …`."""
    where = set()
    for command in phase.gate:
        m = re.match(r"\s*cd\s+(\S+)\s*(?:&&|;)", command)
        where.add(m.group(1).rstrip("/") if m else ".")
    return sorted(where)


def _norm(name):
    return name.lower().replace("_", "-")


def installed(root):
    """What the repository already depends on, normalised: the text of every pyproject.toml
    and package.json near the root, which is plenty to ask "is this name in there"."""
    files = [root / "pyproject.toml", *root.glob("package.json"), *root.glob("*/package.json")]
    return "\n".join(_norm(f.read_text(encoding="utf-8", errors="replace"))
                     for f in files if f.is_file())


def declared(text):
    """Package names the design says it will add, normalised."""
    names = set()
    for line in text.splitlines():
        if DEPENDS_RE.search(line):
            names |= {_norm(m) for m in TICKED_RE.findall(line)}
        for m in INSTALL_RE.finditer(line):
            names |= {_norm(w) for w in m.group(1).split() if not w.startswith("-")}
    return names


def new_dependencies(text, phase, have):
    """Declared packages this repo lacks, that this phase uses without a code example of them.
    A package counts as used when the description names it (`recurring_ical_events.of(…)`);
    an example is a fenced block in the description that mentions it."""
    body = re.split(r"(?m)^###\s+Exit criteria", phase.body)[0]
    blocks = _norm(" ".join(re.findall(r"```.*?```", body, re.S)))
    prose = _norm(re.sub(r"```.*?```", "", body, flags=re.S))
    return sorted(n for n in declared(text)
                  if n not in have and re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", prose)
                  and n not in blocks)


def advisories(text, phases, sizes, design_path="", root=None):
    """Things that make a design risky without making it unrunnable, so `check` can say them
    before a night is spent rather than after. `sizes` is each phase's prompt length in
    bytes, parallel to `phases`. `root` is the target repository, for what it already
    depends on; without it that check is skipped."""
    out = []
    pre = doc_references(preamble(text), design_path)
    if pre:
        out.append(f"The preamble names {len(pre)} document(s) — "
                   + ", ".join(f"`{d}`" for d in pre) + ".\n"
                   "    The preamble reaches every phase, so every phase may go and read "
                   "them. A phase that\n    reads a document has an unbounded prompt. Fold "
                   "what each phase needs into the phase.")
    for i, phase in enumerate(phases, 1):
        quote = skip_requests(phase.body)
        if quote:
            out.append(f"Phase {i} asks for a skipped test — \"{quote}\".\n"
                       "    The test guard rejects an added skip or xfail marker, so this "
                       "phase fails verification\n    for doing what the design told it "
                       "to. Drop the instruction, or run with --allow-test-changes.")
        docs = doc_references(phase.body, design_path)
        if docs:
            out.append(f"Phase {i} names " + ", ".join(f"`{d}`" for d in docs)
                       + " — check the agent is meant to write it, not read it.")
    # A phase that is much bigger than its neighbours, or that carries a lot of criteria, is
    # the shape that fails: one such phase was split in two and went from three failures to
    # committing on the first try. Both thresholds are advice, never an error.
    # Lower middle, so a two-phase design can still flag its larger half; on a long
    # design the choice barely moves.
    median = (sorted(sizes)[(len(sizes) - 1) // 2]
              if sizes and len(sizes) == len(phases) else 0)
    for i, phase in enumerate(phases, 1):
        size = sizes[i - 1] if median else 0
        why = []
        if median and size > 1.6 * median:
            why.append(f"{size / 1024:.1f} KB, {size / median:.1f}x the median prompt")
        if len(phase.criteria) > MANY_CRITERIA:
            why.append(f"{len(phase.criteria)} exit criteria")
        if why:
            out.append(f"Phase {i} is large — " + " and ".join(why)
                       + ". A phase whose title says \"and\" is usually two phases.")
    wide = [i for i, phase in enumerate(phases, 1) if len(toolchains(phase)) >= FULL_STACK]
    if wide:
        out.append(f"Phase(s) {', '.join(map(str, wide))} are gated in more than one toolchain "
                   "(a backend and its UI).\n    Such phases peaked at 74-116k context here, past "
                   "the relay line: expect fresh starts,\n    and keep anything else — a new "
                   "source, a new library — out of them.")
    have = installed(root) if root is not None else None
    for i, phase in enumerate(phases, 1):
        new = new_dependencies(text, phase, have) if have is not None else []
        if new:
            out.append(f"Phase {i} uses " + ", ".join(f"`{n}`" for n in new)
                       + ", which this repo does not depend on yet, with no example.\n"
                       "    The agent will learn its API by trial. Put a short usage snippet "
                       "in the phase: the calls, and what they return.")
    return out


def describe(phases):
    """The `styre check` rendering: every phase with its criteria and gate."""
    out = []
    for p in phases:
        out.append(f"\n{p.title}\n  exit criteria:")
        out += [f"    - {c}" for c in p.criteria]
        out.append("  gate:")
        out += [f"    $ {c}" for c in p.gate]
    return "\n".join(out)
