# Design: M4, the advisor

Today any stop ends the run, and the person reads it in the morning. In the person's own
runs since styre 0.17, 9 stops came from the builder's work: 7 phases too big for one
context, 1 BLOCKED on a design defect and 1 phase with no diff. M4 hands each of those to
the **advisor**, Claude through `claude -p`, which answers with one action. A stop caused by
the model host still ends the run.

Terms used in every phase:

- **Phase**: one `## Phase N: Title` section of the design, built by the builder and
  committed as one commit. Do not call it a task or a step.
- **Gate**: the commands in a phase's `### Gate` block, which styre runs itself before it
  commits. Do not call them checks.
- **Builder**: the local model, through pi. **Advisor**: Claude, through `claude -p`, called
  when a phase stalls.
- **Stall**: a stop caused by the builder's work. The five kinds: the gate still red after
  the fix rounds, a relay that is stuck or past `MAX_RELAYS`, a state file that is missing,
  says BLOCKED or lists unmet criteria, and a green gate with no staged diff.
- **Host failure**: pi exiting non-zero, the idle timeout (rc 124), or an empty response.
  A host failure ends the run as today. The advisor is never called for one.
- **Advice**: the advisor's answer to one stall: an action, a reason and a text.
- **Actions**: `amend` adds text to the phase's prompt and runs the phase again. `split`
  replaces the phase, in this run only, with 2 or 3 smaller phases. `patch` has the advisor
  edit the code itself, then styre gates and commits it. `stop` ends the run with the
  advisor's reason.

Rules for the whole milestone:

| Topic | Decision |
| --- | --- |
| Calls | at most one advice per design phase; a split's new phases share their parent's. A second stall of the same phase stops the run |
| Patches | at most `MAX_PATCHES = 2` per run. Past that, `patch` is not offered |
| The design file | never edited or committed by styre. Advice lives in the run directory only |
| The tree | a stalled attempt's uncommitted work stays in the tree for the next attempt |
| Commits | a phase commit that holds a patch has the trailer `Styre-Advisor: patch`. No commit line names Claude, Anthropic or Claude Code |
| Runtime | stdlib only, Python 3.9+ (`from __future__ import annotations` at the top of each module), pathlib, no POSIX-only shell syntax in `styre/` |
| Modules | one module, one job: the advisor's call and its checks get `styre/advisor.py`, not more `runner.py` |
| Tests | pytest in `tests/`. The end-to-end tests drive the real loop against `tests/fake_pi.py` and `tests/fake_claude.py`. No test calls a real model |
| Comments | short and plain; say why, not what. A new module starts with a docstring saying its one job |
| Errors | one English sentence each, like `design.validate()`'s |

**Repository facts every phase needs** (read from commit 493ee5f; line numbers are from that commit, so search by name in a file an earlier phase changed):

- The gate's first command runs every test under `tests/` (`testpaths = ["tests"]`, `pyproject.toml:49-50`). The second, `uvx ruff check .`, lints the whole tree, tests included.
- Ruff (`pyproject.toml:52-56`): `line-length = 110`, `select = ["E", "F", "W", "I", "UP", "B"]`. The rules that bite:
  - `I001` import order: stdlib, then third party (`pytest`, and `conftest`, as in `tests/test_plan.py:6-15`), then `styre`, one blank line between groups.
  - Inside a group, `import x` lines come before `from x import y` lines. Names in one `from` import are sorted: constants, then classes, then functions.
  - `F401` unused import, `E501` a line over 110 characters, `B006` a mutable default argument.
  - `UP006`/`UP007`: write `list[str]` and `str | None`, never `typing.List` or `typing.Optional`.
- `from __future__ import annotations` is already the first import in `runner.py`, `rundir.py`, `summarize.py`, `claude.py`, `settings.py`, `planner.py`, `design.py`, `acceptance.py`, `timeline.py` and `config.py`.
- It is missing from `prompts.py`, `gitops.py`, `guard.py`, `cli.py` and `state.py`. Before you add a `str | None` annotation to one of those, add the import right after the module docstring. Without it, Python 3.9 raises `TypeError` at import.
- Timeline (`styre/timeline.py:19-50`): `Timeline(path).event(name, **fields)` appends one line `{"ts": ..., "event": name, **fields}` and returns it. `span(name, **fields)` writes `<name>_start`, then `<name>_end` with `seconds`.
- Event names in use: `run_start`, `pi_start`/`pi_end`, `relay`, `gate_start`/`gate_end`, `guard_result`, `acceptance_restored`, `commit`, `phase_end`, `run_end`, `model_call`.
- `RunDir.root` is relative: `RUNS = WORK / "runs"` with `WORK = Path(".styre")` (`styre/rundir.py:21`, `styre/config.py:31`). So `run.log(n).as_posix()` is already relative to the repository root, for example `.styre/runs/20261103-220000/logs/phase1.log`.
- The fixtures in `tests/conftest.py`:
  - `repo` (40-52): a git repo at `tmp_path / "repo"` holding `README.md` and `design.md` = `DESIGN`, with one commit, `initial`. The fixture does not change the test's working directory.
  - `DESIGN` has two phases. `Phase 1: First phase`: body `Do the first thing.`, criteria `["done.txt exists"]`, gate `["test -f done.txt"]`. `Phase 2: Second phase`: criteria `["done.txt still exists"]`, the same gate.
  - `fake_pi` (55-64) and `fake_claude` (67-76) each write a shim into `tmp_path / "bin"` and return `f"{bindir}{os.pathsep}{os.environ['PATH']}"`.
  - `fake_pi` calls `bindir.mkdir()` without `exist_ok`. If `fake_claude` runs first, `fake_pi` raises `FileExistsError`.
  - `styre(*args, plan=None, default="ok", path=None, timeout=120, background=False, env_extra=None, cwd=None)` (89-112) runs `python -m styre` in the repo. It applies `env_extra` last, so `env_extra` overrides any variable.
  - `commits()` (115-121): the repo's commit subjects, newest first.
- `tests/fake_pi.py` picks its action by the base name of the last `@` prompt file, looked up in `$FAKE_PI_PLAN` (the `plan=` dict), else `default`. The phase number is `phase(\d+)` in that name, so `phase1.advice.md` and `phase1.split2.md` are phase 1.
- `tests/fake_pi.py` actions (`act()`, 138-188):
  - `ok`: writes `work{n}.py` and `done.txt`, appends `docs/decisions.md`, writes a DONE state file and `.styre/notes-next.md` = `Notes from phase {n}.`
  - `bad_gate`: writes `work{n}.py`, a DONE state and the notes, but no `done.txt`.
  - `blocked`: writes state BLOCKED with reason `the design does not say which format to use`.
  - Also: `lying`, `nochange`, `skip_test`, `crash` (exit 3), `hang`, `empty`, `grow`, `stuck`.
  - Before acting, every action except `stuck` (and the handoff turn) overwrites `.styre/progress.md` with `Done: ran {name}\nNow: {action}\n`.
  - Each pi invocation's argv is appended to `<run>/pi-argv.jsonl`.
- `tests/fake_claude.py`:
  - It reads stdin and prints the file `$FAKE_CLAUDE_REPLY` names. It prints nothing when the variable is unset or the file is missing.
  - It appends `{"argv": [...], "stdin": "..."}` to `$FAKE_CLAUDE_LOG` and exits with `$FAKE_CLAUDE_EXIT` (default 0).
  - When `$FAKE_CLAUDE_REPLY` names a directory, call k (1-based, counted from the log's lines) prints `<dir>/<k>.json`.
  - When it prints nothing, `claude.call("advisor", ...)` fails with `The advisor call printed output that is not JSON.`
- A good reply is `tests/fixtures/claude_read_tools.json` loaded with `json.loads`, with its `structured_output` replaced by the answer. `claude.call` returns that dict as `result.output`.
- A test that reaches `claude.call` sets `STYRE_CONFIG` to a `styre.json` in `tmp_path` holding `{"frontier": {"command": ["claude"], "timeout": 60}}`, and puts the fake first on `PATH`. Without `STYRE_CONFIG`, `settings.load()` reads `~/.config/styre/styre.json`.
- Add no skip or xfail marker to a test file, not even the Windows marker `tests/test_run_end_to_end.py:10` has: the test guard rejects an added one, and CI runs on Linux and macOS only.

---

## Phase 1: The advisor's call and its checks

Add `styre/advisor.py`: the advice schema, the advisor prompt, one `claude -p` call with
one retry, and the checks on its answer. Nothing calls it yet; the runner uses it in
Phase 2.

The module's interface:

```python
ACTIONS = ("amend", "split", "patch", "stop")
MAX_PATCHES = 2
READ_TOOLS = ["Read", "Grep", "Glob"]

@dataclass
class Stall:
    n: str             # the phase number, as text: "3"
    phase: Phase       # styre.design.Phase
    context: str       # the phase's design excerpt, exactly as its builder prompt has it
    reason: str        # styre's sentence for why the phase stopped
    progress: str      # the builder's progress file, or ""
    gate_report: str   # the last gate failure report, or ""
    diff_stat: str     # `git diff --cached --stat` of the uncommitted work, or ""
    log: str           # path of the phase's readable log, relative to the repo root

@dataclass
class Advice:
    action: str        # one of ACTIONS
    reason: str        # one paragraph for the person
    text: str          # amend: text for the builder; split: the new phase sections;
                       # patch: the diagnosis for the patch call; stop: may be ""
    phases: list       # split only: the new phases, parsed; else []

def schema(actions) -> dict
def split_problems(phase, n, text) -> list[str]
def check(answer, stall, actions) -> tuple[Advice | None, list[str]]
def advise(stall, actions, *, cwd, timeline, log_dir) -> tuple[Advice | None, str | None]
```

- `schema(actions)` returns a JSON schema object: `{"type": "object", "properties":
  {"action": {"type": "string", "enum": list(actions)}, "reason": {"type": "string"},
  "text": {"type": "string"}}, "required": ["action", "reason", "text"],
  "additionalProperties": false}`. `actions` is a sequence of names from `ACTIONS`; the
  enum holds exactly those, in the order given.
- `check(answer, stall, actions)` judges the call's `structured_output`. It returns
  `(Advice, [])` when the answer is good, else `(None, problems)`, one sentence each:
  - `answer` is not a dict, or `action` is not in `actions`:
    `The advice's action must be one of: amend, stop.` (the names joined by `, `).
  - `reason` is missing or blank: `The advice has no reason.`
  - `text` is blank and the action is `amend`, `split` or `patch`:
    `The advice's text is empty; amend, split and patch need it.`
  - action `split`: every sentence `split_problems(stall.phase, stall.n, text)` returns.
- `split_problems(phase, n, text)` parses `text` with `styre.design.parse_phases`. It returns
  one sentence per broken rule, empty when the split is good:
  - 2 or 3 phases: `The split has 1 phase; it must have 2 or 3.`
  - phase k's title starts with `Phase {n}.{k}:`:
    `Split phase 2's title must start with 'Phase 3.2:'.`
  - every sentence `styre.design.validate(phases)` returns, unchanged.
  - the last phase keeps the stalled phase's gate, exit criteria and acceptance tests
    exactly: `The split's last phase must keep the phase's gate unchanged.`, and the same
    sentence with `exit criteria` and `acceptance tests`.
  - no earlier phase has acceptance tests:
    `Split phase 1 has acceptance tests; only the last phase may, and only the original ones.`
- `advise(stall, actions, ...)` calls `claude.call("advisor", advisor_prompt(stall,
  actions), schema(actions), READ_TOOLS, cwd=cwd, timeline=timeline, log_dir=log_dir)`.
  A call error returns `(None, result.error)`. An answer `check()` refuses gets one retry:
  the same prompt, then a blank line, `Your advice was refused:` and the problems, one per
  line. A second refusal returns `(None, problems[0])`. A good answer returns
  `(advice, None)`. This is the planner's retry in `styre/cli.py:115-131`, the same shape.

Add `advisor_prompt(stall, actions)` to `styre/prompts.py`. It states, in this order:

1. The situation: a local model, through the pi coding agent, built one phase of a design
   unattended, and the phase stalled. Nobody is watching; the person reads the run later.
   The advisor reads the repository with Read, Grep and Glob, and edits nothing.
2. The stall: `stall.reason`, then the phase's design excerpt (`stall.context`) inside
   `<phase>` tags, the progress file inside `<progress>` tags (or `(none)`), the gate report
   inside `<gate_report>` tags (or `(none)`), the diff stat inside `<uncommitted>` tags (or
   `(nothing uncommitted)`), and the log's path with the note that its end is the most
   recent.
3. The offered actions, only those in `actions`, one line each on when to choose it:
   - `amend`: the builder lacked a fact, a file, a signature or a rule. `text` is what the
     builder reads before it starts again on the tree as it is now.
   - `split`: the phase is too big for one context. `text` holds 2 or 3 sections in the
     design format, titled `## Phase {n}.1: ...`, `## Phase {n}.2: ...`, each with its text,
     a `### Exit criteria` list and a `### Gate` block. The last one keeps the phase's gate,
     exit criteria and `### Acceptance tests` section unchanged. The earlier ones get their
     own gate, green on their own work, and no acceptance tests.
   - `patch`: one hard part the builder will not get right. `text` is the diagnosis: what is
     wrong and what to change. A second call makes the edit.
   - `stop`: the design is wrong, or the stall needs the person. `reason` says what the
     person has to decide.
4. The rules: the uncommitted work stays in the tree; the design file is not changed; the
   advisor answers once for this phase; `reason` is one paragraph for the person.

**Where**
- `styre/claude.py:50-147` `call(role, prompt, schema, tools, *, cwd, timeline, log_dir,
  timeout=None) -> ClaudeResult`. `ClaudeResult` has `output` (the `structured_output` dict
  or None), `error` (one sentence or None), `usage`, `seconds`. It writes the
  `model_call` timeline event itself.
- `styre/cli.py:100-131` the planner's call and its one retry; copy its shape.
- `styre/planner.py:1-68` a module of the same kind: a docstring, a schema constant and a
  checking function returning sentences.
- `styre/design.py:95-126` `Phase` (`title`, `body`, `criteria`, `gate`, `acceptance`) and
  `parse_phases(text)`. `styre/design.py:160-182` `validate(phases)`.
- `styre/prompts.py:74-124` `planner_prompt(brief, window)`: the style of a frontier
  prompt. Add `advisor_prompt` after it.
- `tests/test_plan.py:31-69` `run_plan()` and `call_stdins()`: how a test sets
  `STYRE_CONFIG`, `PATH`, `FAKE_CLAUDE_REPLY` (a file, or a directory of `1.json`, `2.json`)
  and `FAKE_CLAUDE_LOG`. `tests/test_claude.py` calls `claude.call` directly with a
  `Timeline` and a `log_dir`. `tests/fixtures/claude_read_tools.json` is a real reply
  whose `structured_output` a test can replace.
- New: `styre/advisor.py`, `tests/test_advisor.py`.

Do not change `styre/runner.py`, `styre/claude.py` or `styre/cli.py` in this phase.

**Where, more detail from the source**
- `styre/claude.py:26-43`: `ClaudeUsage` (`tokens_in`, `cached_in`, `cache_write`, `tokens_out`, `thinking`, `cost_usd`, `turns`). `ClaudeResult(output: dict | None = None, error: str | None = None, usage=ClaudeUsage(), seconds=0.0)`.
- `styre/claude.py:61-66`: the argv is `[*frontier.command, "-p", "--output-format", "json", "--json-schema", json.dumps(schema), "--tools", ",".join(tools), "--no-session-persistence", "--permission-mode", "dontAsk"]`. A test finds the tools at `argv[argv.index("--tools") + 1]`.
- `claude.call` writes `log_dir/<role>.<n>.json` and `.err`, and prints a failed call's sentence to stderr itself.
- Every `claude.call` error sentence starts `The {role} call ...`, so the advisor's start `The advisor call ...`. Example: `The advisor call printed output that is not JSON.`
- `styre/cli.py:115-131`, the retry to copy, as it is now:
  ```python
  problems = planner.problems(brief, planned)
  if problems:
      retry = claude.call("planner", prompt + "\n\nYour design was refused:\n" +
                          "\n".join(problems), PLAN_SCHEMA, ["Read", "Grep", "Glob"],
                          cwd=Path.cwd(), timeline=tl, log_dir=run_dir)
      ...
      if retry.error is not None:
          problems = [retry.error]
  ```
- `styre/design.py:29`: `PHASE_RE = re.compile(r"(?m)^##\s+(Phase\s+\d+.*?)\s*$")`. `## Phase 3.1: Title` parses, with `title == "Phase 3.1: Title"`.
- `Phase.criteria` is a list of strings without the `- `. `Phase.gate` is a list of stripped command lines.
- `Phase.acceptance` is a list of `(path, content)` tuples; `content` ends with a newline. Two parses of the same section compare equal with `==`.
- `validate()` numbers phases from 1 within the list it is given. On a split it says `Phase 1 has no '### Gate' code block.`, not `Phase 3.1 ...`. Its sentences: `Phase {i} has no '### Exit criteria' list.`, `Phase {i} has no '### Gate' code block.`, and four about acceptance paths.
- `styre/prompts.py:1-11`: no `from __future__ import annotations`. It imports `hashlib`, `Path`, `AGENTS_BODY` and `DECISIONS`.
- `styre/advisor.py` imports `advisor_prompt` from `styre.prompts`. So `prompts.py` must not import `styre.advisor` (a circular import): read `stall.reason`, `stall.context` and the other fields by attribute.
- `tests/test_claude.py:59-86` `fake_call()`: the pattern for a unit test of a `claude.call` caller with `monkeypatch`.
- Copy from `tests/test_plan.py`: the retry tests (112-129) and `call_stdins` (61-63).
- `@dataclass` is imported as `from dataclasses import dataclass, field`, as in `styre/claude.py:19`.
- Do not touch `tests/conftest.py` or `tests/fake_claude.py` in this phase.

### Acceptance tests

`tests/test_m4_advisor_contract.py`
```python
"""Acceptance: the advisor's call and its checks (styre/advisor.py, prompts.advisor_prompt).

No test calls a real model: tests/fake_claude.py stands in for `claude`.
"""
import json
from pathlib import Path

from styre.advisor import (
    ACTIONS,
    MAX_PATCHES,
    READ_TOOLS,
    Advice,
    Stall,
    advise,
    check,
    schema,
    split_problems,
)

from styre.design import parse_phases
from styre.prompts import advisor_prompt
from styre.timeline import Timeline

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FENCE = "`" * 3
ACCEPT = ("tests/test_thing_contract.py", "def test_thing_contract():\n    assert True\n")


def section(title, criterion="the thing works", gate="pytest -q", accept=None):
    """One phase section in the design format, built line by line."""
    lines = ["## " + title, "Build it.", ""]
    if accept is not None:
        lines += ["### Acceptance tests", "", f"`{accept[0]}`", FENCE + "python", accept[1] + FENCE, ""]
    lines += ["### Exit criteria", f"- {criterion}", "", "### Gate", FENCE, gate, FENCE, ""]
    return "\n".join(lines) + "\n"


PHASE = parse_phases(section("Phase 3: Build the thing", accept=ACCEPT))[0]
FIRST = section("Phase 3.1: The first half", criterion="the first half works", gate="pytest -q tests/a")
LAST = section("Phase 3.2: The second half", accept=ACCEPT)


def stall(**changes):
    fields = {"n": "3", "phase": PHASE, "context": "<the design excerpt for phase 3>",
              "reason": "gate failed: pytest -q, still failing after 2 fix rounds",
              "progress": "", "gate_report": "", "diff_stat": "",
              "log": ".styre/runs/r/logs/phase3.log"}
    fields.update(changes)
    return Stall(**fields)


def test_the_constants():
    assert ACTIONS == ("amend", "split", "patch", "stop")
    assert MAX_PATCHES == 2
    assert READ_TOOLS == ["Read", "Grep", "Glob"]


def test_schema_offers_exactly_the_actions_given_in_order():
    assert schema(["amend", "stop"]) == {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["amend", "stop"]},
                       "reason": {"type": "string"}, "text": {"type": "string"}},
        "required": ["action", "reason", "text"],
        "additionalProperties": False}
    assert schema(("stop", "patch"))["properties"]["action"]["enum"] == ["stop", "patch"]


# --- check -------------------------------------------------------------------------------


def test_check_accepts_a_good_amend():
    advice, problems = check({"action": "amend", "reason": "It lacked the format.", "text": "Use JSON."},
                             stall(), ["amend", "stop"])
    assert problems == []
    assert isinstance(advice, Advice)
    assert (advice.action, advice.reason, advice.text, advice.phases) == (
        "amend", "It lacked the format.", "Use JSON.", [])


def test_check_accepts_a_stop_with_no_text():
    advice, problems = check({"action": "stop", "reason": "The design is wrong.", "text": ""},
                             stall(), ["amend", "stop"])
    assert problems == [] and advice.action == "stop"


def test_check_refuses_an_answer_that_is_not_a_dict():
    advice, problems = check("stop", stall(), ["amend", "stop"])
    assert advice is None
    assert "The advice's action must be one of: amend, stop." in problems


def test_check_refuses_an_action_that_was_not_offered():
    advice, problems = check({"action": "patch", "reason": "r", "text": "t"}, stall(), ["amend", "stop"])
    assert advice is None
    assert problems == ["The advice's action must be one of: amend, stop."]


def test_check_refuses_a_blank_or_missing_reason():
    advice, problems = check({"action": "stop", "reason": "  ", "text": ""}, stall(), ["amend", "stop"])
    assert advice is None and problems == ["The advice has no reason."]
    advice, problems = check({"action": "stop", "text": ""}, stall(), ["amend", "stop"])
    assert advice is None and "The advice has no reason." in problems


def test_check_refuses_an_empty_text_for_amend_split_and_patch():
    for action in ("amend", "split", "patch"):
        advice, problems = check({"action": action, "reason": "r", "text": " "}, stall(), list(ACTIONS))
        assert advice is None, action
        assert "The advice's text is empty; amend, split and patch need it." in problems, action


def test_check_parses_a_good_split():
    advice, problems = check({"action": "split", "reason": "Too big.", "text": FIRST + LAST},
                             stall(), list(ACTIONS))
    assert problems == []
    assert [p.title for p in advice.phases] == ["Phase 3.1: The first half", "Phase 3.2: The second half"]


def test_check_returns_the_split_problems():
    bad = FIRST + section("Phase 3.2: The second half", gate="pytest -q tests/b", accept=ACCEPT)
    advice, problems = check({"action": "split", "reason": "Too big.", "text": bad}, stall(), list(ACTIONS))
    assert advice is None
    assert problems == ["The split's last phase must keep the phase's gate unchanged."]


# --- split_problems ----------------------------------------------------------------------


def test_a_good_split_has_no_problems():
    assert split_problems(PHASE, "3", FIRST + LAST) == []


def test_a_split_needs_2_or_3_phases():
    one = LAST.replace("Phase 3.2:", "Phase 3.1:")
    assert "The split has 1 phase; it must have 2 or 3." in split_problems(PHASE, "3", one)


def test_each_part_title_carries_the_phase_number():
    text = FIRST + LAST.replace("Phase 3.2:", "Phase 3.3:")
    assert split_problems(PHASE, "3", text) == ["Split phase 2's title must start with 'Phase 3.2:'."]


def test_the_split_is_validated_like_a_design():
    no_gate = "\n".join(["## Phase 3.1: No gate", "Build it.", "", "### Exit criteria", "- it works", ""])
    assert "Phase 1 has no '### Gate' code block." in split_problems(PHASE, "3", no_gate + "\n" + LAST)


def test_the_last_part_keeps_the_gate_the_criteria_and_the_acceptance_tests():
    cases = {
        "gate": section("Phase 3.2: The second half", gate="pytest -q tests/b", accept=ACCEPT),
        "exit criteria": section("Phase 3.2: The second half", criterion="something else", accept=ACCEPT),
        "acceptance tests": section("Phase 3.2: The second half"),
    }
    for name, last in cases.items():
        assert split_problems(PHASE, "3", FIRST + last) == [
            f"The split's last phase must keep the phase's {name} unchanged."], name


def test_only_the_last_part_may_have_acceptance_tests():
    first = section("Phase 3.1: The first half", criterion="the first half works", gate="pytest -q tests/a",
                    accept=("tests/test_other_contract.py", "def test_other():\n    assert True\n"))
    assert split_problems(PHASE, "3", first + LAST) == [
        "Split phase 1 has acceptance tests; only the last phase may, and only the original ones."]


# --- advisor_prompt ----------------------------------------------------------------------


def test_advisor_prompt_states_the_stall_in_order():
    s = stall(progress="Done: half of it", gate_report="Gate command failed: `pytest -q`",
              diff_stat=" a.py | 3 +++")
    text = advisor_prompt(s, ["amend", "stop"])
    assert "Read, Grep and Glob" in text
    marks = [s.reason, "<phase>", "<the design excerpt for phase 3>", "<progress>", "Done: half of it",
             "<gate_report>", "Gate command failed", "<uncommitted>", "a.py | 3 +++", s.log]
    positions = [text.index(m) for m in marks]
    assert positions == sorted(positions)


def test_advisor_prompt_says_when_a_part_of_the_stall_is_empty():
    text = advisor_prompt(stall(), ["amend", "stop"])
    assert "(none)" in text and "(nothing uncommitted)" in text


def test_advisor_prompt_names_only_the_offered_actions():
    every = advisor_prompt(stall(), list(ACTIONS))
    some = advisor_prompt(stall(), ["amend", "stop"])
    assert "too big for one context" in every and "A second call makes the edit" in every
    assert "too big for one context" not in some and "A second call makes the edit" not in some
    assert "lacked a fact" in some and "the stall needs the person" in some


# --- advise, through tests/fake_claude.py ------------------------------------------------


def answer(path, output):
    """A `claude -p` result shaped like the captured one, with `output` as its structured output."""
    doc = json.loads((FIXTURES / "claude_read_tools.json").read_text(encoding="utf-8"))
    doc["structured_output"] = output
    path.write_text(json.dumps(doc), encoding="utf-8")


def use_fake(monkeypatch, tmp_path, fake_claude, reply):
    cfg = tmp_path / "styre.json"
    cfg.write_text(json.dumps({"frontier": {"command": ["claude"], "timeout": 60}}), encoding="utf-8")
    monkeypatch.setenv("STYRE_CONFIG", str(cfg))
    monkeypatch.setenv("PATH", fake_claude)
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "calls.log"))
    monkeypatch.setenv("FAKE_CLAUDE_REPLY", str(reply))
    for var in ("FAKE_CLAUDE_EXIT", "FAKE_CLAUDE_SLEEP"):
        monkeypatch.delenv(var, raising=False)


def calls(tmp_path):
    log = tmp_path / "calls.log"
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def run_advise(tmp_path, actions):
    return advise(stall(), actions, cwd=str(tmp_path), timeline=Timeline(tmp_path / "timeline.jsonl"),
                  log_dir=tmp_path / "logs")


def test_advise_returns_a_good_answer_from_one_call(monkeypatch, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    replies.mkdir()
    answer(replies / "1.json", {"action": "amend", "reason": "It lacked the format.", "text": "Use JSON."})
    use_fake(monkeypatch, tmp_path, fake_claude, replies)
    advice, error = run_advise(tmp_path, ["amend", "stop"])
    assert error is None
    assert (advice.action, advice.text) == ("amend", "Use JSON.")
    made = calls(tmp_path)
    assert len(made) == 1
    argv = made[0]["argv"]
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == schema(["amend", "stop"])
    assert made[0]["stdin"] == advisor_prompt(stall(), ["amend", "stop"])
    lines = (tmp_path / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
    assert [e["role"] for e in map(json.loads, lines) if e["event"] == "model_call"] == ["advisor"]


def test_a_refused_answer_gets_one_retry_with_the_problems(monkeypatch, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    replies.mkdir()
    answer(replies / "1.json", {"action": "split", "reason": "Too big.", "text": FIRST + LAST})
    answer(replies / "2.json", {"action": "stop", "reason": "The design is wrong.", "text": ""})
    use_fake(monkeypatch, tmp_path, fake_claude, replies)
    advice, error = run_advise(tmp_path, ["amend", "stop"])
    assert error is None and advice.action == "stop"
    first, second = (c["stdin"] for c in calls(tmp_path))
    assert second.startswith(first)
    assert "Your advice was refused:\nThe advice's action must be one of: amend, stop." in second


def test_a_second_refusal_returns_the_first_problem(monkeypatch, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    replies.mkdir()
    for k in (1, 2):
        answer(replies / f"{k}.json", {"action": "patch", "reason": "r", "text": "t"})
    use_fake(monkeypatch, tmp_path, fake_claude, replies)
    advice, error = run_advise(tmp_path, ["amend", "stop"])
    assert advice is None
    assert error == "The advice's action must be one of: amend, stop."
    assert len(calls(tmp_path)) == 2


def test_a_failed_call_returns_its_sentence_without_a_retry(monkeypatch, tmp_path, fake_claude):
    use_fake(monkeypatch, tmp_path, fake_claude, tmp_path / "no-reply.json")
    advice, error = run_advise(tmp_path, ["amend", "stop"])
    assert advice is None
    assert error == "The advisor call printed output that is not JSON."
    assert len(calls(tmp_path)) == 1
```

### Exit criteria
- `styre/advisor.py` defines `ACTIONS`, `MAX_PATCHES`, `READ_TOOLS`, `Stall`, `Advice`, `schema`, `split_problems`, `check` and `advise` with the signatures above.
- `styre/prompts.py` defines `advisor_prompt(stall, actions)`, which names only the actions in `actions`.
- `tests/test_advisor.py` covers each sentence `check()` and `split_problems()` return, and `advise()`'s good answer, retry and failed call through `tests/fake_claude.py`.
- Nothing outside `styre/advisor.py`, `styre/prompts.py` and `tests/` is edited.

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 2: Stalls go to the advisor: amend and stop

Wire the advisor into the run. A stall calls `advisor.advise()` once, offering `amend` and
`stop`. `stop` ends the run with the advisor's reason. `amend` runs the phase again, on the
tree as it is, with the advice added to its prompt. A host failure ends the run as today.

`run_phase(ctx, n)` returns a `PhaseResult` instead of a string:

```python
@dataclass
class PhaseResult:
    reason: str | None   # None: committed
    stall: bool          # True for the five stall kinds, False for a host failure
    gate_report: str     # the last gate failure's full report, or ""
    rounds: int          # fix rounds used, counted over every attempt of the phase
    relays: int          # relays used, counted over every attempt of the phase
```

Classify in `run_phase` where each `why` is set (`styre/runner.py:293-399`). Host
failures, `stall=False`: the `rc != 0` branch (pi exited, timeout) and the empty-response
branch. Every other `why` is a stall.

Give `run_phase` two keyword arguments, `advice=None` and `after=None`. With `advice` (the
advice's text) and `after` (the stalled attempt's `PhaseResult`), it runs the **amended
attempt**:

- It does not call `clear_progress()`: the progress file is the next attempt's start.
- It writes `run.advice(n)` (new in `styre/rundir.py`: `phase{n}.advice.md`) with
  `advice_prompt(n, phase, advice, read_progress())`, new in `styre/prompts.py`: the
  advice inside `<advice>` tags, the progress file block from `_progress_block()`, and one
  sentence that the tree holds the stalled attempt's work. The first step's prompts are
  `[builder, advice_file]`, a fresh process, step name `advised`.
- `rounds` and `relays` start at `after.rounds` and `after.relays`, so fix-round and relay
  file names continue (`phase1.fix3.md` after `phase1.fix2.md`) and none is overwritten.
  The limits count the amended attempt's own: `--retries` more fix rounds, `MAX_RELAYS`
  more relays.

In `orchestrate` (`styre/runner.py:416-440`), for a stall of a phase not yet advised:

1. Build an `advisor.Stall`: `n=str(n)`, the phase, `ctx.context(n)`, the reason,
   `read_progress()`, `result.gate_report`, `diff_stat()` (new in `styre/gitops.py`:
   `stage_all()`, then `git diff --cached --stat`), and `run.log(n)` relative to the
   repository root.
2. Call `advise(stall, ["amend", "stop"], cwd=Path.cwd(), timeline=tl,
   log_dir=run.root / "logs")`.
3. Write the timeline event `advice` with `phase=n`, `action`, `reason`; for a failed call
   `action=None` and `error` the sentence.
4. Failed call: stop with `Stopped at phase {n}: {reason}. The advisor could not be asked:
   {error} Work is left uncommitted.`
5. `stop`: stop with `Stopped at phase {n}: {reason}. The advisor stopped it: {advice
   reason} Work is left uncommitted.`
6. `amend`: `run_phase(ctx, n, advice=advice.text, after=result)`. A stall of the amended
   attempt stops with `Stopped at phase {n}: {reason}, after the advisor's amend. Work is
   left uncommitted.` and no second call.

A host failure, and a stall when the advisor call is not reached, keep today's message.

`preflight()` (`styre/runner.py:138-196`) prints, when
`shutil.which(settings.load()["frontier"]["command"][0])` is None:
`[warn] Claude Code ('claude') is not on PATH: a stall will stop the run instead of going
to the advisor.` (with the command's name). A `settings.SettingsError` becomes a
`PreflightError` with its message.

`summarize`: a phase's `advice` events become `Phase.advice`, a list of `(action, reason)`
pairs (`styre/summarize.py:173-217`, folded in `read_timeline` at 249-288). A phase with
advice counts in `Phase.problems`. `where_to_look` (591-643) prints, per advice,
`- the advisor chose amend: <reason>`, or `- the advisor could not be asked: <error>`.

The test fixture must never reach a real `claude`. The `styre` fixture
(`tests/conftest.py:89-112`) puts the real `PATH` after the fakes. Make it request the
`fake_claude` fixture (same `bin` directory, so `PATH` already holds both fakes) and set
`STYRE_CONFIG` to a `styre.json` in `tmp_path` holding
`{"frontier": {"command": ["claude"], "timeout": 60}}`, and `FAKE_CLAUDE_LOG` to a file in
`tmp_path`. With no `FAKE_CLAUDE_REPLY`, the fake prints nothing, the call fails, and every
existing stall test stops with its old reason still in the message. Tests pass a reply with
`env_extra={"FAKE_CLAUDE_REPLY": ...}`. A reply is a JSON file shaped like
`tests/fixtures/claude_read_tools.json` with `structured_output` replaced by the advice.

**Where**
- `styre/runner.py:261-406` `run_phase`: the loop at 293-385 sets `why` at each stop;
  the commit at 387-399; `phase_end` at 401-405. `styre/runner.py:416-440` `orchestrate`.
- `styre/runner.py:198-210` `empty_response(events)`.
- `styre/rundir.py:38-86` `RunDir`; add `advice(n)` beside `fix(n, round_)` at 50.
- `styre/prompts.py:127-157` `_progress_block` and `fix_prompt`: copy their shape for
  `advice_prompt`.
- `styre/gitops.py:32-45` `stage_all`, `staged_diff`, `commit`.
- `styre/settings.py:28-59` `load()` and `SettingsError`.
- `styre/summarize.py:173-217` `Phase`, 249-288 `read_timeline`, 591-643 `where_to_look`.
- `tests/conftest.py:67-112` the `fake_claude` and `styre` fixtures.
- `tests/test_run_end_to_end.py:68-111` the stall tests (`bad_gate`, `blocked`, `lying`,
  `nochange`) and 601-616 the relay stalls (`grow`, `stuck`). The fake pi picks its action
  by the last attached prompt's file name, so `{"phase1.advice.md": "ok"}` scripts the
  amended attempt.

**Where, more detail from the source** (commit 493ee5f)
- The `run_phase` loop runs from line 301 to 389 (`while True:` to the last fix-round `print`). The commit block is 391-399.
- Where each `why` is set in `run_phase`:
  - 326, relay stuck: `fresh start {relays - 1} filled its context ...` (stall).
  - 331, past `MAX_RELAYS` (stall).
  - 349, `rc != 0`: `f"pi exited with {rc}" + (" (timeout)" if rc == 124 else "")` (host failure).
  - 354-356, `state_problem(state)` (stall).
  - 357-360, the same branch when `empty_response(events)` (host failure).
  - 374, `f"{short}, still failing after {rounds} fix rounds"` (stall).
  - 394, inside the commit block: `gate passed but the phase changed nothing (no staged diff)` (stall).
- Line 316: `rc == RELAY_RC` (75) is a relay, not a failure. A relayed step that left a state file falls through to the judging at 354.
- `run_phase`'s start, lines 279-300 as they are now:
  ```python
  phase, run, opts, tl = ctx.phase(n), ctx.run, ctx.opts, ctx.tl
  ...
  previous = run.notes(n - 1)
  notes = previous.read_text(encoding="utf-8").strip() if previous.exists() else ""
  builder = run.prompt(n)
  builder.write_text(build_prompt(ctx.context(n), n, phase, notes), encoding="utf-8")
  clear_progress()
  write_acceptance(phase, Path.cwd())  # a difference at phase start is a resume, not an edit
  start_phase_tools(n, phase.gate, opts.gate_timeout)

  task = [builder]          # the prompt files that state the work of the current round
  prompts, session = task, None
  rounds, relays, why, state = 0, 0, None, None
  start_mark = None
  round_relays = 0
  ```
- Line 303: `step = "builder" if rounds == 0 else f"fix {rounds}"`. With `rounds` starting at `after.rounds`, the amended attempt's first step must be named `advised` some other way.
- The two limits: line 330 `if relays > MAX_RELAYS:` and line 373 `if rounds >= opts.retries:`. `MAX_RELAYS = 6` (`styre/config.py:63`). `RunOptions.retries` defaults to `DEFAULT_RETRIES = 2` (`styre/config.py:65`).
- The fresh fix-round prompts, line 386: `fix_prompt(n, phase, full, read_progress())`, attached as `[builder, fix]`. `full` is the report `verify` returned: the value for `PhaseResult.gate_report`.
- `orchestrate`'s loop today, lines 426-432:
  ```python
  committed, stopped = 0, None
  for n in range(opts.from_phase, len(ctx.phases) + 1):
      why = run_phase(ctx, n)
      if why is not None:
          stopped = f"Stopped at phase {n}: {why}. Work is left uncommitted."
          break
      committed += 1
  ```
- The stop message goes into `run_end.stopped`. The summary header prints it (`styre/summarize.py:447-449`), so `run`'s stdout holds it.
- `styre/settings.py:17-18`: `class SettingsError(ValueError)`. `load()` (26-59) returns `{"frontier": {"command": [...], "timeout": int}}`. A missing file returns the default `["claude"]`. A broken file raises, for example, `Settings file {p} is not valid JSON: {e}`.
- `styre/runner.py:10` already imports `shutil`. Add `settings` to the `from styre import __version__` line.
- `styre/cli.py:197-200` turns a `PreflightError` into `sys.exit(str(e))`: the message on stderr, exit 1. `cli.py` needs no change.
- Print the warning on one line, with `print(..., flush=True)`, like the `[warn]` lines at `styre/runner.py:125` and `180`.
- `styre/gitops.py:8-10`: `git(*args)` returns `(returncode, output)`, with stdout and stderr merged (`styre/process.py:265-277`). `gitops.py` has no `from __future__ import annotations`.
- `styre/summarize.py`:
  - `Phase.problems` (206-216) is one `bool(... or ...)` expression.
  - `read_timeline` (249-289) skips an event without `phase` at 260. An `advice` event has `phase`, so it reaches the `elif` chain.
  - `where_to_look` (591-643) writes, per phase with problems, a bold title line, then `- ` lines, then a blank line.
  - The brief's failed-call event has `action=None` and `error`. Fold it so `where_to_look` can print `- the advisor could not be asked: <error>`.
- `tests/conftest.py:89-90`: today the fixture is `def styre(repo, fake_pi, pi_config):`. Put `fake_claude` after `fake_pi` in that list. `fake_pi`'s `bindir.mkdir()` fails if `fake_claude` made the directory first.
- After this phase, every existing stall test reaches the fake `claude`, which prints nothing. Each then stops with `... The advisor could not be asked: The advisor call printed output that is not JSON. Work is left uncommitted.` The substrings they assert (`still failing after 1 fix rounds`, `BLOCKED: ...`, `changed nothing (no staged diff)`, `fresh start 1 filled its context`, `split it`) stay in the message.
- Copy from `tests/test_run_end_to_end.py`: `run_dir` (13-16), `timeline` (205-207), `argvs` and `attached` (502-507).
- Do not touch: `styre/claude.py`, `styre/design.py`, `styre/planner.py`, `styre/cli.py`, `tests/fake_pi.py`, `tests/fake_claude.py`, or any existing test's assertions. Do not offer `patch` or `split` yet.

### Acceptance tests

`tests/test_m4_amend_stop.py`
```python
"""Acceptance: a stall goes to the advisor, which can amend or stop (M4 phase 2).

The whole loop runs against tests/fake_pi.py and tests/fake_claude.py; no test calls a model.
"""
import inspect
import json
from pathlib import Path

from conftest import DESIGN

from styre.design import parse_phases
from styre.gitops import diff_stat
from styre.prompts import advice_prompt
from styre.rundir import RunDir
from styre.runner import PhaseResult, run_phase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BLOCKED = "BLOCKED: the design does not say which format to use"
NOT_JSON = "The advisor call printed output that is not JSON."
STOP = {"action": "stop", "reason": "The design must name the format.", "text": ""}
AMEND = {"action": "amend", "reason": "The builder lacked the format.", "text": "Use JSON for the format."}


def run_dir(repo):
    name = (repo / ".styre" / "latest.txt").read_text(encoding="utf-8").strip()
    return repo / ".styre" / "runs" / name


def timeline(repo):
    lines = (run_dir(repo) / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(ln) for ln in lines]


def events(repo, kind):
    return [e for e in timeline(repo) if e["event"] == kind]


def stopped(repo):
    return events(repo, "run_end")[-1]["stopped"]


def answer(path, output):
    """A `claude -p` result shaped like the captured one, with `output` as its structured output."""
    doc = json.loads((FIXTURES / "claude_read_tools.json").read_text(encoding="utf-8"))
    doc["structured_output"] = output
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def advisor_env(tmp_path, reply):
    """The advisor's settings and the fake's files, all outside the repository."""
    cfg = tmp_path / "advisor-styre.json"
    cfg.write_text(json.dumps({"frontier": {"command": ["claude"], "timeout": 60}}), encoding="utf-8")
    return {"STYRE_CONFIG": str(cfg), "FAKE_CLAUDE_LOG": str(tmp_path / "advisor-calls.log"),
            "FAKE_CLAUDE_REPLY": str(reply)}


def calls(tmp_path):
    log = tmp_path / "advisor-calls.log"
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def offered(call):
    argv = call["argv"]
    return json.loads(argv[argv.index("--json-schema") + 1])["properties"]["action"]["enum"]


def attached(argv):
    return [a[1:].rsplit("/", 1)[-1] for a in argv if a.startswith("@")]


def pi_argvs(repo):
    text = (run_dir(repo) / "pi-argv.jsonl").read_text(encoding="utf-8")
    return [json.loads(ln) for ln in text.splitlines()]


def summary(repo):
    return (run_dir(repo) / "summary.md").read_text(encoding="utf-8")


# --- the interfaces ----------------------------------------------------------------------


def test_phase_result_holds_the_verdict_and_the_counters():
    result = PhaseResult(reason=None, stall=False, gate_report="", rounds=0, relays=0)
    assert (result.reason, result.stall, result.gate_report, result.rounds, result.relays) == (
        None, False, "", 0, 0)


def test_run_phase_takes_advice_and_after():
    params = inspect.signature(run_phase).parameters
    assert params["advice"].default is None and params["after"].default is None


def test_the_advice_prompt_file_is_named_after_the_phase():
    assert RunDir(Path("r")).advice(2) == Path("r") / "phase2.advice.md"


def test_advice_prompt_holds_the_advice_and_the_progress_file():
    phase = parse_phases(DESIGN)[0]
    text = advice_prompt(1, phase, "Use JSON for the format.", "Done: ran phase1.prompt.md")
    assert text.index("<advice>") < text.index("Use JSON for the format.") < text.index("</advice>")
    assert "<your_progress_file>" in text and "Done: ran phase1.prompt.md" in text


def test_diff_stat_lists_the_uncommitted_work(repo, monkeypatch):
    monkeypatch.chdir(repo)
    (repo / "work1.py").write_text("value = 1\n", encoding="utf-8")
    assert "work1.py" in diff_stat()


# --- the run -----------------------------------------------------------------------------


def test_a_stall_asks_the_advisor_once_and_its_stop_ends_the_run(styre, repo, commits, tmp_path,
                                                                 fake_claude):
    reply = answer(tmp_path / "stop.json", STOP)
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "blocked"},
              env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits() == ["initial"]
    assert stopped(repo) == (f"Stopped at phase 1: {BLOCKED}. The advisor stopped it: "
                             "The design must name the format. Work is left uncommitted.")
    made = calls(tmp_path)
    assert len(made) == 1
    assert {"amend", "stop"} <= set(offered(made[0]))  # later phases offer more
    assert BLOCKED in made[0]["stdin"] and "Do the first thing." in made[0]["stdin"]
    assert [(e["phase"], e["action"], e["reason"]) for e in events(repo, "advice")] == [
        (1, "stop", "The design must name the format.")]
    assert "- the advisor chose stop: The design must name the format." in summary(repo)


def test_amend_runs_the_phase_again_from_the_advice_file_and_commits(styre, repo, commits, tmp_path,
                                                                     fake_claude):
    reply = answer(tmp_path / "amend.json", AMEND)
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "blocked", "phase1.advice.md": "ok"},
              env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:2] == ["Phase 2: Second phase", "Phase 1: First phase"]
    text = (run_dir(repo) / "phase1.advice.md").read_text(encoding="utf-8")
    assert "<advice>" in text and "Use JSON for the format." in text
    assert "Done: ran phase1.prompt.md" in text  # the progress file was not cleared
    advised = [a for a in pi_argvs(repo) if "phase1.advice.md" in attached(a)]
    assert [attached(a) for a in advised] == [["phase1.prompt.md", "phase1.advice.md"]]
    steps = [e["step"] for e in events(repo, "pi_end") if e["phase"] == 1]
    assert steps == ["builder", "advised"]
    assert len(calls(tmp_path)) == 1
    assert "- the advisor chose amend: The builder lacked the format." in summary(repo)


def test_a_second_stall_of_the_phase_stops_without_a_second_call(styre, repo, commits, tmp_path,
                                                                 fake_claude):
    reply = answer(tmp_path / "amend.json", AMEND)
    r = styre("run", "design.md", "--quiet",
              plan={"phase1.prompt.md": "blocked", "phase1.advice.md": "blocked"},
              env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits() == ["initial"]
    assert stopped(repo) == (f"Stopped at phase 1: {BLOCKED}, after the advisor's amend. "
                             "Work is left uncommitted.")
    assert len(calls(tmp_path)) == 1
    assert len(events(repo, "advice")) == 1


def test_a_failed_advisor_call_stops_with_the_reason_and_the_calls_sentence(styre, repo, commits,
                                                                            tmp_path, fake_claude):
    env = advisor_env(tmp_path, tmp_path / "no-reply.json")  # missing: the fake prints nothing
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "blocked"}, env_extra=env)
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits() == ["initial"]
    assert stopped(repo) == (f"Stopped at phase 1: {BLOCKED}. The advisor could not be asked: "
                             f"{NOT_JSON} Work is left uncommitted.")
    assert [(e["action"], e["error"]) for e in events(repo, "advice")] == [(None, NOT_JSON)]
    assert f"- the advisor could not be asked: {NOT_JSON}" in summary(repo)


def test_a_host_failure_never_reaches_the_advisor(styre, repo, commits, tmp_path, fake_claude):
    reply = answer(tmp_path / "amend.json", AMEND)
    r = styre("run", "design.md", "--quiet", default="crash", env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 1, r.stdout + r.stderr
    assert stopped(repo) == "Stopped at phase 1: pi exited with 3. Work is left uncommitted."
    assert calls(tmp_path) == []
    assert events(repo, "advice") == []


def test_the_amended_attempt_continues_the_fix_round_numbers(styre, repo, commits, tmp_path,
                                                             fake_claude):
    reply = answer(tmp_path / "amend.json", AMEND)
    plan = {"phase1.prompt.md": "bad_gate", "phase1.fix1.md": "bad_gate", "phase1.fix2.md": "bad_gate",
            "phase1.advice.md": "bad_gate", "phase1.fix3.md": "ok"}
    r = styre("run", "design.md", "--quiet", plan=plan, env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:2] == ["Phase 2: Second phase", "Phase 1: First phase"]
    assert all((run_dir(repo) / f"phase1.fix{k}.md").exists() for k in (1, 2, 3))
    stdin = calls(tmp_path)[0]["stdin"]
    assert "<gate_report>" in stdin and "Gate command failed: `test -f done.txt`" in stdin
    assert "<uncommitted>" in stdin and "work1.py" in stdin


def test_preflight_warns_when_the_advisor_command_is_not_on_path(styre, repo, tmp_path):
    cfg = tmp_path / "missing-claude.json"
    cfg.write_text(json.dumps({"frontier": {"command": ["no-such-claude-m4"], "timeout": 60}}),
                   encoding="utf-8")
    r = styre("run", "design.md", "--quiet", env_extra={"STYRE_CONFIG": str(cfg)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert ("[warn] Claude Code ('no-such-claude-m4') is not on PATH: a stall will stop the run "
            "instead of going to the advisor.") in r.stdout + r.stderr


def test_a_broken_styre_json_stops_preflight(styre, repo, commits, tmp_path):
    cfg = tmp_path / "broken.json"
    cfg.write_text("{ not json", encoding="utf-8")
    r = styre("run", "design.md", "--quiet", env_extra={"STYRE_CONFIG": str(cfg)})
    assert r.returncode == 1
    assert f"Settings file {cfg} is not valid JSON" in r.stderr
    assert commits() == ["initial"]
```

### Exit criteria
- `run_phase` returns a `PhaseResult`, and a host failure has `stall=False`.
- A stall calls the advisor once with the actions `amend` and `stop`, and the timeline holds one `advice` event for it.
- `stop` ends the run with the advisor's reason in the stop message.
- `amend` runs the phase again from `phaseN.advice.md`, without clearing the progress file, and commits it when its gate is green.
- A second stall of the same phase stops the run without a second advisor call.
- A failed advisor call stops the run with the original reason and the call's sentence.
- An end-to-end test covers each of the four bullets above, and every existing test still passes.
- `summary.md` names the advisor's action and reason under "Where to look".

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 3: Patch

Offer `patch` while the run has made fewer than `advisor.MAX_PATCHES` patches. On
`patch`, a second advisor call edits the code, styre restores the acceptance tests and runs
the gate, and green commits the phase with the trailer `Styre-Advisor: patch`. Red stops
the run.

Add to `styre/advisor.py`:

```python
PATCH_TOOLS = ["Read", "Grep", "Glob", "Edit", "Write", "Bash"]
PATCH_SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}},
                "required": ["summary"], "additionalProperties": False}

def patch(stall, advice, *, cwd, timeline, log_dir) -> str | None
```

`patch()` calls `claude.call("advisor", patch_prompt(stall, advice.text), PATCH_SCHEMA,
PATCH_TOOLS, cwd=cwd, timeline=timeline, log_dir=log_dir)` and returns `result.error`
(None on success). It is not retried: a failed call may already have edited the tree, and
the gate, not the answer, decides. `patch_prompt(stall, diagnosis)` in `styre/prompts.py`
states: the diagnosis inside `<diagnosis>` tags; the phase's design excerpt and gate
commands; edit the tree so the gate passes; run the gate commands with Bash to check; do not
edit, skip or delete tests (styre's test guard rejects it); do not edit the acceptance test
files (styre writes them back); do not commit, switch branches or touch `.styre/`; return a
`summary` of what was changed.

In `orchestrate`:

- Count patches per run. Offer `["amend", "patch", "stop"]` while the count is below
  `MAX_PATCHES`, else `["amend", "stop"]`.
- On `patch`: call `patch()`. A failed call stops with `Stopped at phase {n}: {reason}. The
  advisor's patch call failed: {error} Work is left uncommitted.` Otherwise
  `styre.acceptance.write(phase, Path.cwd())`, logging restored paths as an
  `acceptance_restored` event with `step="patch"`, then `verify(phase, run.log(n), ...,
  step="patch")`. Red stops with `Stopped at phase {n}: {reason}. The advisor's patch left
  the gate red: {short} Work is left uncommitted.` and no builder fix round. Green: stage,
  and with a staged diff commit `f"{phase.title}\n\nStyre-Advisor: patch"`; write the
  `commit` event with `patch=True` and a `phase_end` event with `status="committed"`.
- Move the commit block of `run_phase` (`styre/runner.py:387-399`) into one function both
  paths call, so the "no staged diff" rule and the `commit` event stay in one place.

`styre/gitops.py:44` `commit(message)` passes the message to `git commit -m`; a message
with a blank line and a trailer works unchanged. Check it in a test with
`git log -1 --format=%B`.

`summarize`: a `commit` event with `patch=True` sets `Phase.patched`. `where_to_look` prints
`- the advisor patched it: the commit carries Styre-Advisor: patch`, and the phase table's
status cell reads `committed (patch)`.

`tests/fake_claude.py` learns to edit: when `$FAKE_CLAUDE_REPLY` is a directory and
`<dir>/<k>.files/` exists for call k, it copies that tree into its working directory before
it replies. Update its docstring. A patch test then uses a reply directory with `1.json`
(the advice, action `patch`), `2.json` (the patch call's answer, `{"summary": "..."}`) and
`2.files/done.txt`.

**Where**
- `styre/advisor.py` from Phase 1: `advise`, `check`, `schema`.
- `styre/runner.py` `orchestrate` and the advice handling from Phase 2; `run_phase`'s commit
  block, near the end of the function.
- `styre/guard.py:46-94` `verify(phase, log, gate_timeout=None, allow_test_changes=False,
  timeline=None, phase_n=None, step=None)` returns None or `(short, full)`.
- `styre/acceptance.py:12-31` `write(phase, root) -> list[str]`, the paths it restored.
- `styre/summarize.py` `Phase`, `read_timeline`, `phase_table` (around 462-470),
  `where_to_look`.
- `tests/fake_claude.py:20-44` `main()`: the reply-directory branch at 28-35.
- `tests/test_run_end_to_end.py`: the advisor tests from Phase 2.

**Where, more detail from the source** (commit 493ee5f; Phase 2 moved the `runner.py` lines, so search by name)
- The commit block today (`styre/runner.py:391-399`):
  ```python
  if why is None:
      stage_all()
      if not has_staged_changes():
          why = "gate passed but the phase changed nothing (no staged diff)"
      else:
          commit(phase.title)
          sha = head_sha()
          tl.event("commit", phase=n, sha=sha, subject=phase.title)
          print(f"    ✓ committed {sha[:7]}  {phase.title}", flush=True)
  ```
- The restore and gate inside the loop today (`styre/runner.py:362-368`), the shape the patch path repeats with `step="patch"`:
  ```python
  edited = write_acceptance(phase, Path.cwd())
  if edited:
      tl.event("acceptance_restored", phase=n, step=step, paths=edited)
      print(f"    acceptance tests restored: {', '.join(edited)}", flush=True)
  failure = verify(phase, log, gate_timeout=opts.gate_timeout,
                   allow_test_changes=opts.allow_test_changes, timeline=tl,
                   phase_n=n, step=step)
  ```
- `runner.py` imports `acceptance.write` as `write_acceptance` (line 16).
- `verify` builds `short` as `f"gate failed: {first[:60]}{more}"` (`styre/guard.py:86`), for example `gate failed: test -f done.txt`. On a green gate it runs `stage_all()` and the test guard, whose `short` is `test guard: skipped or removed tests`.
- `styre/gitops.py:44-45`: `commit(message)` runs `git("commit", "-q", "-m", message)` and returns the exit code. `head_sha()` is at 52-53.
- `styre/summarize.py:282-283`: the `commit` branch of `read_timeline` sets only `sha`.
- `styre/summarize.py:465`: the table row's status cell is `p.status or "?"`.
- `tests/fake_claude.py:23-27` counts `k`, the log's lines before this call, so this call is number `k + 1`. Lines 28-35 pick `<dir>/<k + 1>.json`.
- Copy the files with `shutil.copytree(src, Path.cwd(), dirs_exist_ok=True)`, before the `sys.stdout.write` at line 40. `dirs_exist_ok` exists since Python 3.8. Without it `copytree` raises `FileExistsError`, because the working directory exists.
- `claude.call` starts the fake with `cwd=cwd` (`styre/claude.py:76`), so the fake's working directory is the repository root.
- Copy from: the helpers in `tests/test_m4_amend_stop.py` (`answer`, `advisor_env`, `calls`, `offered`).
- Do not touch: `split` (Phase 4), `styre/claude.py`, the design file. No commit message gets a `Co-Authored-By` or any line that names Claude.

### Acceptance tests

`tests/test_m4_patch.py`
```python
"""Acceptance: the advisor's patch (M4 phase 3).

The whole loop runs against tests/fake_pi.py and tests/fake_claude.py; no test calls a model.
"""
import json
import subprocess
from pathlib import Path

from conftest import DESIGN
from styre.advisor import PATCH_SCHEMA, PATCH_TOOLS, Advice, Stall, patch

from styre.design import parse_phases
from styre.prompts import patch_prompt
from styre.timeline import Timeline

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FENCE = "`" * 3
NOT_JSON = "The advisor call printed output that is not JSON."
PATCH_ADVICE = {"action": "patch", "reason": "One hard part.", "text": "Create done.txt."}
EDIT_TOOLS = "Read,Grep,Glob,Edit,Write,Bash"


def run_dir(repo):
    name = (repo / ".styre" / "latest.txt").read_text(encoding="utf-8").strip()
    return repo / ".styre" / "runs" / name


def events(repo, kind):
    lines = (run_dir(repo) / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, lines) if e["event"] == kind]


def stopped(repo):
    return events(repo, "run_end")[-1]["stopped"]


def answer(path, output):
    """A `claude -p` result shaped like the captured one, with `output` as its structured output."""
    doc = json.loads((FIXTURES / "claude_read_tools.json").read_text(encoding="utf-8"))
    doc["structured_output"] = output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def edit(replies, k, name, text):
    """What the fake's call k writes into its working directory before it answers."""
    target = replies / f"{k}.files" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def advisor_env(tmp_path, reply):
    """The advisor's settings and the fake's files, all outside the repository."""
    cfg = tmp_path / "advisor-styre.json"
    cfg.write_text(json.dumps({"frontier": {"command": ["claude"], "timeout": 60}}), encoding="utf-8")
    return {"STYRE_CONFIG": str(cfg), "FAKE_CLAUDE_LOG": str(tmp_path / "advisor-calls.log"),
            "FAKE_CLAUDE_REPLY": str(reply)}


def use_fake(monkeypatch, tmp_path, fake_claude, reply):
    for name, value in advisor_env(tmp_path, reply).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PATH", fake_claude)
    for var in ("FAKE_CLAUDE_EXIT", "FAKE_CLAUDE_SLEEP"):
        monkeypatch.delenv(var, raising=False)


def calls(tmp_path):
    log = tmp_path / "advisor-calls.log"
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def flag(call, name):
    argv = call["argv"]
    return argv[argv.index(name) + 1]


def offered(call):
    return json.loads(flag(call, "--json-schema"))["properties"]["action"]["enum"]


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def use_design(repo, text):
    (repo / "design.md").write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "brief"], cwd=repo, check=True)


def make_stall():
    return Stall(n="1", phase=parse_phases(DESIGN)[0], context="<the design excerpt for phase 1>",
                 reason="gate failed: test -f done.txt, still failing after 0 fix rounds",
                 progress="", gate_report="", diff_stat="", log=".styre/runs/r/logs/phase1.log")


ADVICE = Advice(action="patch", reason="One hard part.", text="Create done.txt in the root.", phases=[])


# --- the interfaces ----------------------------------------------------------------------


def test_the_patch_call_constants():
    assert PATCH_TOOLS == ["Read", "Grep", "Glob", "Edit", "Write", "Bash"]
    assert PATCH_SCHEMA == {"type": "object", "properties": {"summary": {"type": "string"}},
                            "required": ["summary"], "additionalProperties": False}


def test_patch_prompt_holds_the_diagnosis_the_phase_and_its_gate():
    text = patch_prompt(make_stall(), "Create done.txt in the root.")
    assert text.index("<diagnosis>") < text.index("Create done.txt in the root.") < text.index("</diagnosis>")
    assert "<the design excerpt for phase 1>" in text
    assert "test -f done.txt" in text


def test_patch_edits_through_the_fake_and_returns_none(monkeypatch, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    answer(replies / "1.json", {"summary": "Wrote done.txt."})
    edit(replies, 1, "done.txt", "done\n")
    work = tmp_path / "work"
    work.mkdir()
    use_fake(monkeypatch, tmp_path, fake_claude, replies)
    error = patch(make_stall(), ADVICE, cwd=str(work), timeline=Timeline(tmp_path / "timeline.jsonl"),
                  log_dir=tmp_path / "logs")
    assert error is None
    assert (work / "done.txt").read_text(encoding="utf-8") == "done\n"
    (call,) = calls(tmp_path)
    assert flag(call, "--tools") == EDIT_TOOLS
    assert json.loads(flag(call, "--json-schema")) == PATCH_SCHEMA
    assert call["stdin"] == patch_prompt(make_stall(), "Create done.txt in the root.")


def test_a_failed_patch_call_returns_its_sentence_and_is_not_retried(monkeypatch, tmp_path, fake_claude):
    use_fake(monkeypatch, tmp_path, fake_claude, tmp_path / "no-reply.json")
    error = patch(make_stall(), ADVICE, cwd=str(tmp_path), timeline=Timeline(tmp_path / "timeline.jsonl"),
                  log_dir=tmp_path / "logs")
    assert error == NOT_JSON
    assert len(calls(tmp_path)) == 1


# --- the run -----------------------------------------------------------------------------


def test_a_green_patch_commits_the_phase_with_the_trailer(styre, repo, commits, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    answer(replies / "1.json", PATCH_ADVICE)
    answer(replies / "2.json", {"summary": "Wrote done.txt."})
    edit(replies, 2, "done.txt", "done\n")
    r = styre("run", "design.md", "--quiet", "--retries", "0", plan={"phase1.prompt.md": "bad_gate"},
              env_extra=advisor_env(tmp_path, replies))
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:2] == ["Phase 2: Second phase", "Phase 1: First phase"]
    body = git(repo, "log", "-1", "--format=%B", "HEAD~1")
    assert body.strip() == "Phase 1: First phase\n\nStyre-Advisor: patch"
    assert "Claude" not in body and "Anthropic" not in body
    decide, change = calls(tmp_path)
    assert flag(decide, "--tools") == "Read,Grep,Glob" and "patch" in offered(decide)
    assert flag(change, "--tools") == EDIT_TOOLS
    assert [e["patch"] for e in events(repo, "commit") if e["phase"] == 1] == [True]
    assert [e["status"] for e in events(repo, "phase_end") if e["phase"] == 1][-1] == "committed"
    assert [e["command"] for e in events(repo, "gate_end") if e.get("step") == "patch"] == [
        "test -f done.txt"]
    assert not (run_dir(repo) / "phase1.fix1.md").exists()
    summary = (run_dir(repo) / "summary.md").read_text(encoding="utf-8")
    assert "committed (patch)" in summary
    assert "- the advisor patched it: the commit carries Styre-Advisor: patch" in summary


def test_a_red_patch_stops_the_run_and_commits_nothing(styre, repo, commits, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    answer(replies / "1.json", PATCH_ADVICE)
    answer(replies / "2.json", {"summary": "Changed nothing useful."})  # no 2.files: done.txt stays missing
    r = styre("run", "design.md", "--quiet", "--retries", "0", plan={"phase1.prompt.md": "bad_gate"},
              env_extra=advisor_env(tmp_path, replies))
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits() == ["initial"]
    assert stopped(repo).startswith("Stopped at phase 1: gate failed: test -f done.txt")
    assert stopped(repo).endswith("The advisor's patch left the gate red: gate failed: test -f done.txt "
                                  "Work is left uncommitted.")
    assert [e["step"] for e in events(repo, "pi_end") if e["phase"] == 1] == ["builder"]
    assert len(calls(tmp_path)) == 2


def test_a_failed_patch_call_stops_the_run(styre, repo, commits, tmp_path, fake_claude):
    replies = tmp_path / "replies"
    answer(replies / "1.json", PATCH_ADVICE)  # no 2.json: the patch call prints nothing
    r = styre("run", "design.md", "--quiet", "--retries", "0", plan={"phase1.prompt.md": "bad_gate"},
              env_extra=advisor_env(tmp_path, replies))
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits() == ["initial"]
    assert stopped(repo).endswith(f"The advisor's patch call failed: {NOT_JSON} Work is left uncommitted.")


def three_phase_design():
    lines = ["# Three phases", "", "Preamble every phase needs.", ""]
    for n, name in ((1, "One"), (2, "Two"), (3, "Three")):
        lines += [f"## Phase {n}: {name}", f"Make p{n}.txt.", "", "### Exit criteria", f"- p{n}.txt exists",
                  "", "### Gate", FENCE, f"test -f p{n}.txt", FENCE, ""]
    return "\n".join(lines) + "\n"


def test_after_two_patches_patch_is_no_longer_offered(styre, repo, commits, tmp_path, fake_claude):
    use_design(repo, three_phase_design())
    replies = tmp_path / "replies"
    for k, n in ((1, 1), (3, 2)):
        answer(replies / f"{k}.json", PATCH_ADVICE)
        answer(replies / f"{k + 1}.json", {"summary": f"Wrote p{n}.txt."})
        edit(replies, k + 1, f"p{n}.txt", f"{n}\n")
    answer(replies / "5.json", {"action": "stop", "reason": "Two patches are enough.", "text": ""})
    r = styre("run", "design.md", "--quiet", "--retries", "0", default="bad_gate",
              env_extra=advisor_env(tmp_path, replies))
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits()[:2] == ["Phase 2: Two", "Phase 1: One"]
    made = calls(tmp_path)
    assert len(made) == 5
    assert "patch" in offered(made[0]) and "patch" in offered(made[2])
    assert "patch" not in offered(made[4]) and {"amend", "stop"} <= set(offered(made[4]))
```

### Exit criteria
- `advisor.patch()` uses `PATCH_TOOLS`, and the decision call keeps `READ_TOOLS`.
- A green patch commits the phase with the subject `{phase.title}` and the trailer `Styre-Advisor: patch`, and nothing in the message names Claude.
- A red patch stops the run and commits nothing.
- After two patches in one run, the next advice offers only `amend` and `stop`.
- An end-to-end test covers each of the three bullets above.
- `summary.md` shows `committed (patch)` for a patched phase.

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 4: Split

Offer `split` too. On `split`, styre runs the advisor's 2 or 3 phases, the **parts**, in
place of the stalled phase, in this run only. Each part is built, gated and committed like a
phase, with its own commit titled with the part's title. The parts run as attempts of the
stalled phase's number `n`, reusing the amended attempt from Phase 2, so phase numbers stay
integers everywhere. The design file is not changed.

The offered actions become `["amend", "split", "patch", "stop"]`, without `patch` once
`MAX_PATCHES` is reached. `advisor.check()` already refuses a bad split with
`split_problems()`, so a part list that reaches the runner is valid: 2 or 3 phases titled
`Phase {n}.1: ...`, the last one with the stalled phase's gate, exit criteria and acceptance
tests.

Give `run_phase` a third keyword argument, `part=None`: a `(k, Phase)` pair. With `part`:

- The phase is the part's `Phase`. Its design excerpt is
  `phase_context(ctx.text, ctx.phases[:n - 1] + [part_phase] + ctx.phases[n:], n)`: the
  index shows the part's title in phase `n`'s place.
- The builder prompt file is `run.split(n, k)` (new in `styre/rundir.py`:
  `phase{n}.split{k}.md`), built with `build_prompt`.
- Notes: part 1 reads `run.notes(n - 1)`, as phase `n` did. Part `k > 1` reads
  `run.notes(n)`, the notes the part before it wrote. After the last part, phase `n + 1`
  reads `run.notes(n)` unchanged.
- Part 1 keeps the progress file, and its first step's prompts are
  `[split_file, advice_file]`, where the advice file is `advice_prompt(n, part_phase, text,
  read_progress())` with `text` one sentence: `The phase was split; you build part 1 of
  {count}, {title}. The parts after it build the rest.` Parts 2 and 3 call
  `clear_progress()` and start from `[split_file]` alone.
- The tools and the gate are the part's: `start_phase_tools(n, part_phase.gate, ...)`,
  `acceptance.write(part_phase, ...)` and `verify(part_phase, ...)`.
- `after` carries the counters from the attempt before, as for amend, so no fix-round or
  relay file is overwritten. The first step's name is `split {k}`.
- The commit is titled `part_phase.title`; `phase_end` has `title=part_phase.title`.

In `orchestrate`, on `split`:

1. Write the timeline event `advice` with `action="split"`, the reason, and `titles`, the
   parts' titles.
2. Delete from the tree each of the stalled phase's acceptance files that exists. The last
   part writes them back at its start; an earlier part's gate must not run them.
3. Run the parts in order with `run_phase(ctx, n, part=(k, part_phase), after=result)`,
   `result` being the attempt before. A stall of a part stops the run with
   `Stopped at phase {n} ({part title}): {reason}, after the advisor's split. Work is left
   uncommitted.` and no advisor call.

`summarize` needs no change for the phase row: it keeps phase `n`'s last `phase_end` and
last `commit`, and sums its time and tokens over the parts. `where_to_look` prints, for a
`split` advice, `- the advisor split it into: ` and the titles joined by `; `.

**Where**
- `styre/runner.py` `run_phase` (its first lines read the phase, `ctx.context(n)` and
  `run.notes(n - 1)`, then call `clear_progress()`, `acceptance.write` and
  `start_phase_tools`), `orchestrate`, and the advice handling from Phases 2 and 3.
- `styre/design.py:146-157` `preamble`, `phase_context(text, phases, n)`.
- `styre/rundir.py:38-86` `RunDir`, with `advice(n)` from Phase 2; 144-150
  `start_phase_tools`; 152-155 `clear_progress`.
- `styre/acceptance.py:12-31` `write(phase, root)`: the paths it writes are
  `phase.acceptance`'s.
- `styre/summarize.py` `where_to_look`, with the advice lines from Phase 2.
- `tests/test_run_end_to_end.py`: the advisor tests from Phases 2 and 3. The fake pi picks
  its action by the last attached prompt's name: `phase1.advice.md` for part 1's first step,
  `phase1.split2.md` for part 2's.

**Where, more detail from the source** (commit 493ee5f; Phases 2 and 3 moved the `runner.py` lines, so search by name)
- `styre/design.py:152-157`: `phase_context(text, phases, n)` returns the preamble, then `## The phases of this design`, one `- {p.title}` line per phase with `  <- yours` after phase `n`'s, then `## {phase.title}` and `phase.body`. `phases[n - 1]` is the phase it prints in full.
- `styre/prompts.py:26-71`: `build_prompt(context, n, phase, notes)` prints `<notes_from_the_previous_phase>\n{notes or "(none)"}`. The decisions heading is `## Phase {n}: {phase.short_title}`.
- `Phase.short_title` (`styre/design.py:105-108`) is the text after the first `:`, so a part titled `Phase 1.1: First half` gets the heading `## Phase 1: First half`. The fake pi reads that heading with `appending a "## Phase \d+: (.*?)" section`.
- `styre/rundir.py:144-154`: `start_phase_tools(n, gate, gate_timeout)` writes `.styre/phase.json` and deletes `.styre/phase{n}.gates.jsonl`. `clear_progress()` deletes `.styre/progress.md`.
- `run.state(n)`, `run.notes(n)`, `run.log(n)`, `run.events(n)` and `run.sessions(n)` take the integer `n`, so all parts share phase `n`'s files. `collect(run, n)` moves each part's notes over `run.notes(n)`.
- Delete an acceptance file with `(Path.cwd() / path).unlink(missing_ok=True)` (`missing_ok` exists since Python 3.8), for each `path, _content in phase.acceptance`.
- `advice.phases` holds the parsed parts (`styre.design.Phase`) that `check()` built. `Stall.phase` stays the design's phase `n`.
- Copy from: the helpers in `tests/test_m4_amend_stop.py` (`answer`, `advisor_env`, `calls`, `offered`, `attached`, `pi_argvs`).
- Do not touch: the design file, `styre/design.py`, `styre/claude.py`, `tests/fake_pi.py`. Phase numbers stay integers in every event.

### Acceptance tests

`tests/test_m4_split.py`
```python
"""Acceptance: the advisor's split (M4 phase 4).

The whole loop runs against tests/fake_pi.py and tests/fake_claude.py; no test calls a model.
"""
import inspect
import json
import subprocess
from pathlib import Path

from conftest import DESIGN

from styre.rundir import RunDir
from styre.runner import run_phase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FENCE = "`" * 3
BLOCKED = "BLOCKED: the design does not say which format to use"
CONTRACT_PATH = "tests/test_phase1_contract.py"
CONTRACT = "def test_phase1_contract():\n    assert True\n"


def section(title, criterion, gate, accept=None):
    """One phase section in the design format, built line by line."""
    lines = ["## " + title, "Build this part.", ""]
    if accept is not None:
        lines += ["### Acceptance tests", "", f"`{accept[0]}`", FENCE + "python", accept[1] + FENCE, ""]
    lines += ["### Exit criteria", f"- {criterion}", "", "### Gate", FENCE, gate, FENCE, ""]
    return "\n".join(lines) + "\n"


# The last part keeps phase 1's criterion and gate from tests/conftest.py's DESIGN.
SPLIT = (section("Phase 1.1: First half", "work1.py exists", "test -f work1.py")
         + section("Phase 1.2: Second half", "done.txt exists", "test -f done.txt"))
TITLES = ["Phase 1.1: First half", "Phase 1.2: Second half"]
CONTRACT_SPLIT = (section("Phase 1.1: Prepare", "the contract file is not in the tree",
                          "test ! -f " + CONTRACT_PATH)
                  + section("Phase 1.2: Finish", "done.txt exists", "test -f done.txt",
                            accept=(CONTRACT_PATH, CONTRACT)))


def contract_design():
    """The conftest design with an acceptance test in phase 1."""
    return DESIGN.replace(
        "### Exit criteria\n- done.txt exists\n",
        "### Acceptance tests\n\n`" + CONTRACT_PATH + "`\n" + FENCE + "python\n" + CONTRACT + FENCE
        + "\n\n### Exit criteria\n- done.txt exists\n")


def run_dir(repo):
    name = (repo / ".styre" / "latest.txt").read_text(encoding="utf-8").strip()
    return repo / ".styre" / "runs" / name


def events(repo, kind):
    lines = (run_dir(repo) / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, lines) if e["event"] == kind]


def stopped(repo):
    return events(repo, "run_end")[-1]["stopped"]


def answer(path, output):
    """A `claude -p` result shaped like the captured one, with `output` as its structured output."""
    doc = json.loads((FIXTURES / "claude_read_tools.json").read_text(encoding="utf-8"))
    doc["structured_output"] = output
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def advisor_env(tmp_path, reply):
    """The advisor's settings and the fake's files, all outside the repository."""
    cfg = tmp_path / "advisor-styre.json"
    cfg.write_text(json.dumps({"frontier": {"command": ["claude"], "timeout": 60}}), encoding="utf-8")
    return {"STYRE_CONFIG": str(cfg), "FAKE_CLAUDE_LOG": str(tmp_path / "advisor-calls.log"),
            "FAKE_CLAUDE_REPLY": str(reply)}


def calls(tmp_path):
    log = tmp_path / "advisor-calls.log"
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def offered(call):
    argv = call["argv"]
    return json.loads(argv[argv.index("--json-schema") + 1])["properties"]["action"]["enum"]


def attached(argv):
    return [a[1:].rsplit("/", 1)[-1] for a in argv if a.startswith("@")]


def pi_argvs(repo):
    text = (run_dir(repo) / "pi-argv.jsonl").read_text(encoding="utf-8")
    return [json.loads(ln) for ln in text.splitlines()]


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def use_design(repo, text):
    (repo / "design.md").write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "brief"], cwd=repo, check=True)


# --- the interfaces ----------------------------------------------------------------------


def test_run_phase_takes_a_part():
    assert inspect.signature(run_phase).parameters["part"].default is None


def test_a_part_prompt_file_is_named_after_the_phase_and_the_part():
    assert RunDir(Path("r")).split(1, 2) == Path("r") / "phase1.split2.md"


# --- the run -----------------------------------------------------------------------------


def test_a_two_part_split_commits_each_part_in_order(styre, repo, commits, tmp_path, fake_claude):
    reply = answer(tmp_path / "split.json",
                   {"action": "split", "reason": "Too big for one context.", "text": SPLIT})
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "blocked"},
              env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:3] == ["Phase 2: Second phase", "Phase 1.2: Second half", "Phase 1.1: First half"]
    made = calls(tmp_path)
    assert len(made) == 1 and offered(made[0]) == ["amend", "split", "patch", "stop"]
    assert [(e["action"], e["titles"]) for e in events(repo, "advice")] == [("split", TITLES)]
    names = [attached(a) for a in pi_argvs(repo)]
    assert ["phase1.split1.md", "phase1.advice.md"] in names and ["phase1.split2.md"] in names
    steps = [e["step"] for e in events(repo, "pi_end") if e["phase"] == 1]
    assert steps == ["builder", "split 1", "split 2"]
    gates = [(e["step"], e["command"]) for e in events(repo, "gate_end") if e["phase"] == 1]
    assert gates == [("split 1", "test -f work1.py"), ("split 2", "test -f done.txt")]
    d = run_dir(repo)
    one = (d / "phase1.split1.md").read_text(encoding="utf-8")
    assert "- Phase 1.1: First half  <- yours" in one and "- Phase 2: Second phase" in one
    assert "<notes_from_the_previous_phase>\n(none)" in one
    assert "Notes from phase 1." in (d / "phase1.split2.md").read_text(encoding="utf-8")
    assert "Notes from phase 1." in (d / "phase2.prompt.md").read_text(encoding="utf-8")
    assert "you build part 1 of 2" in (d / "phase1.advice.md").read_text(encoding="utf-8")
    summary = (d / "summary.md").read_text(encoding="utf-8")
    assert "- the advisor split it into: Phase 1.1: First half; Phase 1.2: Second half" in summary


def test_only_the_last_part_runs_with_the_phase_acceptance_tests(styre, repo, commits, tmp_path,
                                                                 fake_claude):
    use_design(repo, contract_design())
    reply = answer(tmp_path / "split.json",
                   {"action": "split", "reason": "Too big for one context.", "text": CONTRACT_SPLIT})
    r = styre("run", "design.md", "--quiet", plan={"phase1.prompt.md": "blocked"},
              env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 0, r.stdout + r.stderr
    assert commits()[:3] == ["Phase 2: Second phase", "Phase 1.2: Finish", "Phase 1.1: Prepare"]
    assert git(repo, "show", f"HEAD~1:{CONTRACT_PATH}") == CONTRACT
    assert CONTRACT_PATH not in git(repo, "show", "--name-only", "--format=", "HEAD~2")


def test_a_stalled_part_stops_the_run_without_a_second_call(styre, repo, commits, tmp_path, fake_claude):
    reply = answer(tmp_path / "split.json",
                   {"action": "split", "reason": "Too big for one context.", "text": SPLIT})
    r = styre("run", "design.md", "--quiet",
              plan={"phase1.prompt.md": "blocked", "phase1.advice.md": "blocked"},
              env_extra=advisor_env(tmp_path, reply))
    assert r.returncode == 1, r.stdout + r.stderr
    assert commits() == ["initial"]
    assert stopped(repo) == (f"Stopped at phase 1 (Phase 1.1: First half): {BLOCKED}, after the "
                             "advisor's split. Work is left uncommitted.")
    assert len(calls(tmp_path)) == 1
```

### Exit criteria
- A split answer runs its parts in order, with one commit each, titled with the part's title.
- Each part runs its own gate, and the last part's gate, exit criteria and acceptance tests are the stalled phase's.
- Part 2 reads part 1's notes, and the phase after the split reads the last part's notes.
- A stall of a part stops the run, names the part's title, and makes no second advisor call.
- `summary.md` lists the parts' titles under "Where to look".
- An end-to-end test covers a two-part split that commits, and one where a part stalls.

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 5: Docs

Describe the advisor where a reader of styre looks for how a run works. Docs only.

- `CLAUDE.md`: add `styre/advisor.py` to the Files table. In "What happens per phase", step
  7: a stall goes to the advisor; a host failure stops the run. Under "Decisions that are
  settled", the bullet "Until a role exists, its judgement is the director's": the advisor
  now decides what a stall needs; reviewing a run stays the director's until M5.
- `docs/architecture.md`: in the "One phase" flowchart (lines 64-89), the stall edges
  (relay stuck, BLOCKED or missing state, no diff, retries used up) lead to "the advisor:
  amend, split, patch or stop"; the host-failure edges (pi exited non-zero or went silent,
  empty response) still lead to stop. Add `advisor.py` to the module table (lines 49-63).
  Change line 39-41: the director no longer decides what every stop means.
- `skills/styre/DIRECTOR.md` rule 3: on a stop, read the advice first (`summary.md`, "Where
  to look"). "Stuck twice on the same work: the director writes that part itself" stays,
  for a phase the advisor stopped.
- `skills/styre/SKILL.md` step 3, "Stop": a stop after advice names the action and its
  reason; a patch commit carries `Styre-Advisor: patch`.
- `README.md` line 19: the advisor is built; the reviewer is not.
- `docs/lessons.md`: nothing; there is no new measured failure yet.

**Where: the lines to change, as they are now** (commit 493ee5f)
- `CLAUDE.md:34-60` is the Files table, one row per file: `` | `styre/claude.py` | ... | `` (line 37). Put the `styre/advisor.py` row near it, with what the module holds after Phases 1-4.
- `CLAUDE.md:119-121`, step 7 of "What happens per phase":
  > 7. Green and a non-empty diff → one commit titled with the phase. Otherwise the run stops,
  >    the work stays uncommitted, and `--from-phase N` resumes in the same run directory when
  >    the design is the same.
- `CLAUDE.md:177-179`, the bullet under "Decisions that are settled":
  > - **Until a role exists, its judgement is the director's** (`skills/styre/DIRECTOR.md`):
  >   deciding what a stop means and reviewing a run stay with the person and the interactive
  >   assistant until M4 (advisor) and M5 (reviewer) take them over.
- `docs/architecture.md:39-41`:
  > The director and the model host are outside styre. The director makes every decision that
  > needs judgement: what the design says, what a stop means, whether the result is good. The
  > model host is wherever pi's config points.
- `docs/architecture.md:47-63`: the module table. Rows read `` | `claude.py` | ... | ``-style, without the `styre/` prefix. Today there is no `claude.py`, `settings.py` or `planner.py` row; add only `advisor.py`.
- `docs/architecture.md:67-89`, the edges of the "One phase" flowchart that end in `stop`, as they are now:
  ```
      relays -- no --> stop
      ended -- "pi exited non-zero,<br/>or went silent" --> stop
      state -- "BLOCKED, missing,<br/>or empty response" --> stop
      diff -- no --> stop
      retries -- no --> stop(["stop: work left uncommitted"])
  ```
  - Line 79 joins a stall (BLOCKED, missing) and a host failure (empty response) in one edge. Split it into two edges.
  - Line 88 is where the `stop` node gets its label. Keep `stop(["stop: work left uncommitted"])` on one remaining edge.
  - Write the new node's label with `amend, split, patch or stop` on one line, with no `<br/>` inside that phrase.
- `skills/styre/DIRECTOR.md:15-18`, rule 3:
  > 3. **The director runs the runs.** It starts approved designs in order, and on a stop fixes
  >    the phase text — adds what the builder was hunting for, or splits the phase — and resumes,
  >    between phases, never under a running one. Stuck twice on the same work: the director
  >    writes that part itself and says so in the commit.
- `skills/styre/SKILL.md:25-28`, step 3:
  > 3. **Stop.** Read the stop reason (`styre summarize`, its "Where to look") and that phase's
  >    archived progress file, nothing more. Then the ladder in `DIRECTOR.md` rule 3. To change a
  >    phase: let the running phase commit or stop, stop the run, edit and commit the design,
  >    `styre run <design> --from-phase N`. Never edit a design under a live run.
- `README.md:19-21`:
  > > v2 is in progress. The planner (`styre plan`) is built. The advisor and the reviewer are
  > > not. Reference setup: Qwen3.8-27B through pi, and Claude Code on Opus 5.5. The plan and
  > > its milestones are in [`docs/v2.md`](docs/v2.md).
- The texts the run prints, for the docs to quote. Stop messages:
  - `The advisor stopped it: {reason}`
  - `The advisor could not be asked: {error}`
  - `, after the advisor's amend.`
  - `, after the advisor's split.`
  - `The advisor's patch left the gate red: {short}`
  - `The advisor's patch call failed: {error}`
- The "Where to look" lines:
  - `- the advisor chose amend: <reason>`
  - `- the advisor could not be asked: <error>`
  - `- the advisor patched it: the commit carries Styre-Advisor: patch`
  - `- the advisor split it into: <titles>`
- No test reads these documents today, apart from the acceptance test below.
- Do not touch: any file under `styre/` or `tests/`, `docs/lessons.md`, `docs/v2.md`, the ADRs, `GLOSSARY.md`.

### Acceptance tests

`tests/test_m4_docs.py`
```python
"""Acceptance: the docs describe the advisor (M4 phase 5)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ["CLAUDE.md", "docs/architecture.md", "skills/styre/DIRECTOR.md", "skills/styre/SKILL.md", "README.md"]


def read(rel):
    """The document with every run of whitespace made one space, so a rewrapped line still matches."""
    return " ".join((ROOT / rel).read_text(encoding="utf-8").split())


def test_claude_md_lists_the_advisor_module():
    assert "`styre/advisor.py`" in read("CLAUDE.md")


def test_architecture_names_the_advisor_module_and_its_actions():
    text = read("docs/architecture.md")
    assert "`advisor.py`" in text
    assert "amend, split, patch or stop" in text


def test_director_rule_3_reads_the_advice_first_and_keeps_stuck_twice():
    text = read("skills/styre/DIRECTOR.md")
    assert "Where to look" in text
    assert "Stuck twice on the same work" in text


def test_the_skill_names_the_patch_trailer():
    assert "Styre-Advisor: patch" in read("skills/styre/SKILL.md")


def test_readme_no_longer_says_the_advisor_is_not_built():
    assert "The advisor and the reviewer are" not in read("README.md")


def test_no_doc_credits_claude_with_a_commit():
    for rel in DOCS:
        text = read(rel)
        assert "Co-Authored-By" not in text and "Generated with Claude Code" not in text, rel
```

### Exit criteria
- Each file in the list above says what its bullet asks, and no other file is edited.
- No doc names Claude, Anthropic or Claude Code as the author of a commit.

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```
