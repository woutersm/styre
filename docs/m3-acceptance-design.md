# Design: M3 — acceptance tests

M2's benchmark left 8 of 242 reference tests failing. Five were interfaces the planned design
named exactly and the builder wrote differently (`from_tokens` missing from
`trene.backends.garmin`, `AuthError` taking no message); three were rules the brief stated.
All eight were named in the briefs. A test written from the brief catches each of them while
the phase runs. M3 adds those **acceptance tests** to the design and has styre write and
protect them.

Terms used in every phase:

- **Design**: the document styre runs, split into phases. A **brief** is a design without the
  implementation help; a **planned design** is a brief after `styre plan` added it.
- **Gate**: the commands in a phase's `### Gate` block, which styre runs itself before it
  commits. Do not call them "checks": `styre check` validates a design.
- **Acceptance test**: a test in a phase's section of the design, for an interface or a rule
  the brief states. The planner or the person writes it; it runs in that phase's gate.
- **Reference test**: a test in the benchmark's held-out suite. It never runs during a run.
- **Builder**: the local model, through pi. **Planner**: Claude, through `claude -p`.

| Topic | Decision |
| --- | --- |
| Runtime | stdlib only, Python 3.9+ (`from __future__ import annotations` at the top of each module), pathlib, no POSIX-only shell syntax in `styre/` |
| Modules | one module, one job: writing acceptance files gets `styre/acceptance.py`, not more `runner.py` |
| Tests | pytest in `tests/`. The end-to-end tests drive the real loop against `tests/fake_pi.py`; no test calls a real model |
| Comments | short and plain; say why, not what. Every module starts with a docstring saying its one job |
| Errors | one English sentence each, like `design.validate()`'s |

The section format every phase works with. A phase may have an `### Acceptance tests` section,
placed after the phase's text and before `### Exit criteria`. It holds one or more files. Each
file is a line holding only its path in backticks, then a fenced code block with the file's
whole content:

````markdown
### Acceptance tests

`tests/test_accept_phase2.py`
```python
from trene.backends.garmin import from_tokens


def test_from_tokens_is_in_garmin():
    assert callable(from_tokens)
```
````

---

## Phase 1: Acceptance tests in the design format

Parse the `### Acceptance tests` section into the `Phase` object, and refuse a malformed one.

**Where**
- `styre/design.py:85-97` `class Phase` (dataclass: `title`, `body`, `criteria`, `gate`;
  property `short_title`). Add a field `acceptance: list[tuple[str, str]]`, default empty:
  `(path, content)` pairs in document order.
- `styre/design.py:99-113` `parse_phases(text)`. It already splits a phase body into sections
  with `SECTION_RE` and keys them by lowercased heading (`named`). Read
  `named.get("acceptance tests", "")`.
- `styre/design.py:81` `FENCE_RE = re.compile(r"```[a-z]*\n(.*?)```", re.S)`: the gate's
  fence pattern. An acceptance block's info string can be `python`, `ts`, `tsx`; match a path
  line, then the fence that follows it.
- `styre/design.py:130-136` `validate(phases)`: returns a list of one-sentence problems, for
  example `"Phase 2 has no '### Gate' code block."`.
- `tests/test_design.py`: copy the shape of `test_validate_names_the_missing_parts` (line 45)
  and `test_parses_the_example_design` (line 17).

**Parsing.** A path line is a line whose stripped text is one backticked token
(`` `tests/test_accept_phase2.py` ``). The content is the first fenced block after it, before
the next path line; keep it exactly, with a trailing newline. A path line with no block
before the next path line or the section's end is kept as `(path, None)` so `validate` can
name it.

**`validate(phases)` adds these errors**, one sentence each, naming the phase and the path:
- `Phase 2's acceptance test path '/abs/x.py' must be relative to the repository root.`
  for an absolute path (`PurePosixPath(p).is_absolute()` or a Windows drive like `C:`);
- `Phase 2's acceptance test path '../x.py' leaves the repository.` for any `..` part;
- `Phase 3 repeats the acceptance test path 'tests/test_a.py' from phase 2.` for a path in
  two phases, or twice in one phase;
- `Phase 2's acceptance test 'tests/test_a.py' has no code block.` for `(path, None)`.

A phase with no section has `acceptance == []` and passes as today. Do not check whether the
path exists in the repository: if an acceptance file replaces an existing test file, the
test functions it removes already trip the test guard.

**Tests** (in `tests/test_design.py`): a design with two files in one phase parses into two
pairs with their exact content; a phase without the section has `[]`; each of the four errors
above appears for its case; the existing example design still validates with no problems.

### Exit criteria
- `parse_phases` fills `Phase.acceptance` with `(path, content)` pairs, and `[]` without the section
- `validate` reports each of the four acceptance errors as one sentence, and nothing for a good section
- the existing design tests pass unchanged

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 2: The planner writes acceptance tests

`styre plan` asks the planner for an acceptance-tests section per phase.

**Where**
- `styre/prompts.py:74-119` `planner_prompt(brief, window)`: the planner's instructions,
  ending with the brief in `<brief>` tags. Add an acceptance-tests bullet to the list "For each
  phase, add under its text:".
- `styre/planner.py:35-71` `problems(brief, planned)`: read only. It already refuses an answer
  that drops a brief line, so a brief's own acceptance tests survive planning, and its
  `validate(pph)` call already applies phase 1's new errors to the planned design.
- `tests/test_prompts.py`: the existing prompt tests.
- `tests/test_plan.py:84` `test_good_answer_commits_the_planned_design`: how a fake planner
  answer is set up with the `fake_claude` and `plan_repo` fixtures.

**What the planner prompt adds**, as its own bullet in the "For each phase" list, in these
words or tighter:

- an `### Acceptance tests` section, placed after the phase's text and before its exit
  criteria: one new test file, a line holding only its path in backticks, then a fenced block
  with the whole file. Write one test per interface the brief names for this phase (import it
  from the module the brief says, call it with the signature the brief gives, construct each
  error class with the arguments the brief shows) and one test per rule the brief states with
  an exact outcome (a sentence, an exit code, a refusal). Nothing the brief does not state.
  Use the repository's test framework and conventions, and put the file where this phase's
  gate command collects it. Each path must be new, and never a path another phase uses. If
  the brief already has an `### Acceptance tests` section, keep it as it is; you may add
  files to it.

**Tests**: the prompt holds the new bullet (assert on two or three of its phrases, not the
whole text). In `tests/test_plan.py`, a fake planner answer that keeps a brief's acceptance
section and adds a second file is accepted and committed; one that drops a line of the
brief's acceptance section is refused.

### Exit criteria
- the planner prompt asks for an acceptance-tests section per phase, for the brief's interfaces and stated rules only
- a planned design that keeps the brief's acceptance tests and adds files is committed; one that drops a line of them is refused

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 3: styre writes and restores acceptance tests in a run

At the start of a phase, and again before each of styre's own gate runs, styre writes that
phase's acceptance files from the design. An edit by the builder is recorded, then undone.

**Where**
- New module `styre/acceptance.py` with one function, `write(phase, root) -> list[str]`: for
  each `(path, content)` in `phase.acceptance`, create the parent directories, compare the
  file on disk with `content`, write `content` (UTF-8, `newline=""` so line endings stay as
  written), and return the paths whose file existed with different content, in order. A file
  that did not exist yet is written and not returned.
- `styre/runner.py:292` `start_phase_tools(n, phase.gate, opts.gate_timeout)`: call
  `acceptance.write(phase, Path.cwd())` on the line before it. Ignore its return value there:
  at phase start a difference is a resume, not an edit.
- `styre/runner.py:360` `failure = verify(...)`: on the line before it, call `write` again;
  when it returns paths, `tl.event("acceptance_restored", phase=n, step=step, paths=edited)`
  and print `    acceptance tests restored: <paths joined by ", ">`.
- `styre/agents.py:44-45`, the rule "Never skip, delete or weaken a test…". Add a rule after
  it, in these words or tighter: "The phase's acceptance tests come from the approved design,
  and styre writes them back before it runs the gate. Run them, watch them fail, then write the
  code. Never edit one. If an acceptance test contradicts the phase text, call `styre_finish`
  with `BLOCKED`, naming the test and the line it contradicts."
- `tests/test_run_end_to_end.py` and `tests/conftest.py`: the `styre`, `repo` and `commits`
  fixtures run the real loop against `tests/fake_pi.py`. `conftest.py:12` `DESIGN` is the
  fake design; `FAKE_PI_PLAN` (`conftest.py:103`) picks fake pi's action per prompt name, as in
  `test_the_test_guard_rejects_a_skip_marker` (line 73).
- `tests/fake_pi.py:139-170`: the actions (`empty`, `blocked`, `bad_gate`, `skip_test`, …).
  Add one, `edit_acceptance`, that does what `ok` does and also appends a line to every file
  under the working tree whose name starts with `test_accept`.

The builder's own `styre_gate` tool does not restore: it runs the tree as the builder left it.
A builder that edited a test can then say DONE, styre's gate fails on the restored file, and a
fix round follows. That is what the report counts. Do not change `styre/pi_extensions/`.

The written files are part of the phase's diff, so they are committed in the phase's one
commit with no extra step. `--from-phase N` writes them again when phase N starts.

**Tests**: `acceptance.write` creates a missing file and returns `[]`, returns the path of a
file it overwrote, returns `[]` for an identical file, and keeps CRLF content byte for byte.
End to end, with a design whose phase 1 has an acceptance file: the file is in phase 1's
commit; with `edit_acceptance`, the timeline has an `acceptance_restored` event naming the
path, and the committed file equals the design's content. The AGENTS.md block holds the new
rule (`tests/test_agents_file.py` shows how it is read).

### Exit criteria
- `acceptance.write` writes each file and returns exactly the paths whose existing content differed
- a run writes a phase's acceptance files at its start and before each styre gate run, and commits them with the phase
- a builder's edit to an acceptance file is logged as `acceptance_restored` and does not survive into the commit
- the AGENTS.md block tells the builder never to edit an acceptance test and to report BLOCKED on a contradiction

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 4: Acceptance edits in the report

`summary.md` shows each acceptance test the builder edited, and how often.

**Where**
- `styre/summarize.py:191` the `Phase` record's fields (`guard_problems: list[str]`, …). Add
  `acceptance_edits: list[str] = field(default_factory=list)`, and add it to the `problems`
  property (lines 206-215) so a phase with an edit shows under "Where to look".
- `styre/summarize.py:247-286` `read_timeline()`: add a branch for `kind ==
  "acceptance_restored"` that extends `phase_of(summary.phases, n).acceptance_edits` with
  `e.get("paths") or []`.
- `styre/summarize.py:587-637` `where_to_look()`: after the guard lines (line 602), add per
  phase `- acceptance test edited by the builder and restored ({times}x): {path}`, grouped
  with `unique()` like the guard problems.
- `tests/test_summarize.py`: the existing tests; copy their timeline-writing helpers.

Do not change `evals/`: a benchmark result keeps the run's `.styre/`, so its `summary.md`
carries the count.

**Tests**: a timeline with two `acceptance_restored` events for one path renders one "Where to
look" line with `(2x)`; a run without them renders as before.

### Exit criteria
- `summary.md` lists each acceptance test the builder edited, with how many times, under "Where to look"
- the report of a run without acceptance edits is unchanged

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 5: Docs

Describe acceptance tests where styre's docs describe each mechanism, and say "gate" where
the README says "checks".

**Where**
- `README.md`: the phrases "your checks" and "runs your checks" (find them with
  `grep -n "checks" README.md`) become "your gate" and "runs the gate"; keep `styre check`,
  which is the command's name. Add a short section after the description of `styre plan`:
  what an acceptance test is, that `styre plan` writes them per phase for named interfaces and
  stated rules, that the person reviews them with the plan, that styre writes them at phase
  start and back before every gate run, and that a builder that finds one wrong reports
  BLOCKED.
- `CLAUDE.md`: in "Goal and scope" and "Decisions that are settled", the test guard is "a stop
  until M3"; it now stays a stop until the executor is replaced, because M3 kept v1's
  executor. Add `styre/acceptance.py` to the Files table in the table's style, and a row for
  `GLOSSARY.md` and `docs/adr/` (the project's terms, and the decisions behind M3).
- `docs/architecture.md`: where it describes the phase loop and the gate, add the two writes
  of acceptance files (phase start, before each styre gate run).
- `skills/styre/writing-designs.md`: add the `### Acceptance tests` section to the format it
  shows: placement, path line plus fenced block, new paths only, and that the gate must
  collect the file.

Write in the same style as the surrounding text: short sentences, the number where there is
one. Do not add a changelog.

### Exit criteria
- the README says "gate" for the commands that end a phase and describes acceptance tests
- CLAUDE.md's test-guard wording matches the kept executor, and its Files table lists `styre/acceptance.py`, the glossary and the ADRs
- architecture.md and writing-designs.md describe the acceptance section and when styre writes it

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
! grep -n "your checks" README.md
```
