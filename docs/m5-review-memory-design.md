# Design: M5, the reviewer and memory

Two roles join the run. The **reviewer**, Claude through `claude -p`, reads a finished run
once and names its findings. A finding with a test that fails on the finished tree is fixed in
the same run, by one **fix phase**. The **curator**, the local model through its
OpenAI-compatible endpoint, keeps the memory after each green phase, and every later
phase gets it in its prompt. Director reviews of the last four finished designs found 1 to 3 real bugs
each; this makes that review, and its fixes, part of the run.

Terms used in every phase:

- **Phase**: one `## Phase N: Title` section of the design, built by the builder and
  committed as one commit. Do not call it a task or a step.
- **Gate**: the commands in a phase's `### Gate` block, which styre runs itself before it
  commits. Do not call them checks.
- **Builder**: the local model, through pi. **Advisor**, **planner**, **reviewer**: Claude,
  through `claude -p`. **Curator**: the local model, one completion through its endpoint.
- **Finding**: one problem the reviewer names. **Proven**: its test command exits non-zero
  on the finished tree. **Fix phase**: the phase styre adds at the end of a run, in that run
  only, to make the proven findings' tests pass.
- **Memory**: `docs/memory.md` in the target repository, at most 4,000 characters of short
  facts about the repository that later phases should know. Do not call it notes or the
  decisions log; those are other files.

Rules for the whole milestone:

| Topic | Decision |
| --- | --- |
| Reviewer | once, after a run commits its last design phase; read-only tools; never edits the tree. A failed review call leaves the run's exit code as it was |
| Findings | at most 5. A finding without a test, or whose test passes, is reported only. The proven ones get one fix phase; there is no second review |
| Fix phase | a `Phase` built by styre: the proven tests are its acceptance tests (restored before every gate), its gate is the last design phase's gate plus the tests' commands. It runs like any phase, the advisor included |
| Curator | after a phase's gate is green and its diff is staged, before its commit; reads the memory, the phase's `notes-next.md` and its new lines of `docs/decisions.md`; the new memory goes into the phase's commit |
| Curator off | when styre's pi config names no default model with a `baseUrl`, the curator is off and nothing is called, like relay and resume |
| Curator failure | one retry, then the memory stays as it was and the run goes on; the timeline and the report say so |
| Readers | the builder gets the memory in every prompt; the planner, advisor and reviewer prompts point them at the memory file |
| Runtime | stdlib only, Python 3.9+ (`from __future__ import annotations` at the top of each module), pathlib, `urllib.request` for HTTP, no POSIX-only shell syntax in `styre/` |
| Modules | one module, one job: `styre/local.py` the endpoint call, `styre/curator.py` the memory, `styre/reviewer.py` the review. Not more `runner.py` |
| Tests | pytest in `tests/`. The end-to-end tests drive the real loop against `tests/fake_pi.py`, `tests/fake_claude.py` and a fake endpoint. No test calls a real model |
| Comments | short and plain; say why, not what. A new module starts with a docstring saying its one job |
| Errors | one English sentence each, like `design.validate()`'s |
| Commits | no commit line names Claude, Anthropic or Claude Code |

---

## Phase 1: The local endpoint and the curator

Add `styre/local.py`, one completion against the builder's own model, and `styre/curator.py`,
which turns a phase's notes and decisions into the next memory. Nothing calls them yet; the
runner does in Phase 2.

`styre/local.py`:

```python
@dataclass
class LocalResult:
    text: str | None = None      # the answer's message content, or None
    error: str | None = None     # one English sentence, or None
    tokens_in: int = 0
    cached_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0

def endpoint(config_dir=None) -> tuple[str, str | None, str] | None
def complete(role, prompt, *, timeline, log_dir, timeout=600, max_tokens=2000) -> LocalResult
```

- `endpoint(config_dir)` reads `settings.json` (`defaultProvider`, `defaultModel`) and
  `models.json` (`providers[name]`: `baseUrl`, `apiKey`, `api`) from `config_dir`, default
  `styre.config.PI_CONFIG_DIR`. It returns `(base_url without a trailing "/", api_key,
  model_id)`, or None when a file is missing or unreadable, the provider or its `baseUrl` is
  missing, or `api` is set to anything but `"openai-completions"`. An `apiKey` starting with
  `$` names an environment variable, as pi reads it; an unset one gives `None`.
- `complete(role, prompt, ...)` posts to `{base_url}/chat/completions` with
  `{"model": model_id, "messages": [{"role": "user", "content": prompt}], "max_tokens":
  max_tokens, "temperature": 0, "reasoning_effort": "none", "stream": false}`, the header
  `Content-Type: application/json`, and `Authorization: Bearer <key>` when there is a key.
  `reasoning_effort: "none"` turns the model's thinking off; the reference host honours it.
  `timeout` is the socket timeout in seconds.
- The answer's text is `choices[0].message.content`. Its usage is `usage.prompt_tokens`,
  `usage.prompt_tokens_details.cached_tokens` and `usage.completion_tokens`; a missing field
  counts 0.
- Errors, one sentence each, in `LocalResult.error`: no endpoint (`The curator has no
  endpoint: styre's pi config names no default model with a baseUrl.`, with the role's
  name), an HTTP error with its status, a timeout, a connection refused, a body that is not
  JSON, and an answer with no message content.
- Every call writes the response body to `log_dir/<role>.<k>.json` (k counts that role's
  files, as `styre/claude.py:69` does) and one `model_call` timeline event with `role`,
  `model`, `tokens_in`, `cached_in`, `tokens_out`, `seconds`, `ok` and `error`, the fields
  `claude.call` writes. `summarize` already makes a row per role from these events.

`styre/curator.py`:

```python
MEMORY = Path("docs/memory.md")
MEMORY_LIMIT = 4000

def curate(memory, notes, decisions, *, timeline, log_dir) -> tuple[str | None, str | None]
def check(text) -> str | None
```

- `check(text)` returns None for a good memory, else one sentence: empty
  (`The memory is empty.`) or over the limit (`The memory is 4,321 characters; the limit is
  4,000.`, with the real count). Before checking, `curate` strips the text and one
  surrounding code fence, if the model wrapped its answer in one.
- `curate(memory, notes, decisions, ...)` calls `local.complete("curator",
  curator_prompt(memory, notes, decisions), ...)`. A call error returns `(None, error)`. A
  text `check` refuses gets one retry: the same prompt, a blank line, `Your memory was
  refused:` and the sentence. A second refusal returns `(None, sentence)`. A good text
  returns `(text, None)`.

Add `curator_prompt(memory, notes, decisions)` to `styre/prompts.py`. It says: you keep a
repository's memory, short facts a coding agent needs in later phases; here is the memory,
the notes the phase that just finished wrote for the next one, and its new lines in the
decisions log, each in its own tags (`<memory>`, `<notes>`, `<decisions>`, `(none)` when
empty); keep a fact that stays true of the repository (a convention, a command, a trap, where
something lives) and drop one about a single phase's progress; one fact per line, as a `- `
bullet, grouped under at most five `## ` headings; at most 4,000 characters; answer with the
whole new file and nothing else.

Tests use a fake endpoint: add a `fake_endpoint` fixture to `tests/conftest.py` that starts
`http.server.ThreadingHTTPServer` on `127.0.0.1` port 0 in a daemon thread, answers each
`POST /v1/chat/completions` from a list of replies the test sets (a JSON body and a status),
records each request body, and shuts down after the test. It returns an object with
`base_url`, `replies` and `requests`. A test points a pi config directory at it:
`models.json` `{"providers": {"fake": {"baseUrl": "<base_url>", "apiKey": "$FAKE_KEY",
"models": [{"id": "m", "contextWindow": 1000}]}}}` and `settings.json`
`{"defaultProvider": "fake", "defaultModel": "m"}`.

**Where**
- `evals/probe.py:39-52` `endpoint(config_dir)`: the same lookup, written for the probe; copy
  its rules into `styre/local.py`, do not import from `evals/`. `evals/probe.py:86-131`
  `stream()`: the request headers and the usage fields.
- `styre/config.py:27-30` `PI_CONFIG_DIR` (set by `$STYRE_PI_CONFIG_DIR` in tests) and
  89-99 `context_window()`, which reads the same two files.
- `styre/claude.py:50-147` `call()`: the shape to copy for the log file, the `model_call`
  event and the one-sentence errors.
- `styre/timeline.py:25-35` `Timeline.event(event, **fields)`.
- `styre/prompts.py:74-127` `planner_prompt`: the style of a model prompt.
- `tests/conftest.py:67-86` the `fake_claude` and `pi_config` fixtures; add `fake_endpoint`
  after them. `tests/test_claude.py:89-112` tests one call against a fixture reply and
  reads its timeline event; copy its shape.
- New: `styre/local.py`, `styre/curator.py`, `tests/test_local.py`, `tests/test_curator.py`.

Do not change `styre/runner.py` in this phase.

### Exit criteria
- `styre/local.py` defines `LocalResult`, `endpoint` and `complete` as above, using only the standard library.
- `styre/curator.py` defines `MEMORY`, `MEMORY_LIMIT`, `curate` and `check` as above.
- `styre/prompts.py` defines `curator_prompt(memory, notes, decisions)`.
- `tests/conftest.py` has the `fake_endpoint` fixture, and the tests cover: an endpoint found and a `$NAME` key read from the environment, each case where `endpoint` returns None, a good completion with its `model_call` event, each error sentence, and `curate`'s good answer, retry and failure.
- Nothing outside `styre/local.py`, `styre/curator.py`, `styre/prompts.py` and `tests/` is edited.

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 2: Memory in the run

Call the curator for every green phase, put its memory in the phase's commit, and give the
memory to every later phase.

In `commit_phase(ctx, n, phase, patched=False)` (`styre/runner.py:487-500`), the one
commit path for the builder, a patch and a split's parts:

1. `stage_all()`; with no staged changes, return the "no staged diff" reason as now. Check
   this before the curator runs, so a memory change alone never makes a commit.
2. When `local.endpoint()` is not None: read `MEMORY` (`""` when missing), the phase's notes
   (`ctx.run.notes(n)`, `""` when missing), and the phase's new decisions lines: the added
   lines of `git diff --cached -U0 -- docs/decisions.md`, without the `+` and without the
   `+++` header. Call `curator.curate(...)` with `log_dir=ctx.run.root / "logs"`.
3. A good answer: write it to `MEMORY` with a trailing newline, and `git add` it. Write a
   `memory` timeline event with `phase=n`, `ok=True`, `chars`. A failure: leave the file,
   write `memory` with `ok=False` and `error`, and print `    memory unchanged: <error>`.
4. Commit as now.

The builder's prompt carries the memory. `build_prompt(context, n, phase, notes,
memory="")` (`styre/prompts.py:26-71`) gets a `<memory>` block after the notes block, with
one line before it: `Facts earlier phases learned about this repository (docs/memory.md):`,
and `(none yet)` when empty. `run_phase` reads `MEMORY` when it writes a builder prompt
(`styre/runner.py:324` and `:365`). `cmd_check` (`styre/cli.py:162`) passes the file's text
too, so the printed sizes include it.

`planner_prompt` and `advisor_prompt` get one sentence: `docs/memory.md`, when it exists,
holds facts earlier phases learned about this repository; read it first.

`summarize`: a `memory` event with `ok=False` adds `- memory unchanged: <error>` to that
phase under "Where to look", and counts in `Phase.problems` (`styre/summarize.py:174-222`,
folded in `read_timeline` at 252-300, printed in `where_to_look` at 603-666). Curator calls
already appear under "Model calls" through their `model_call` events; check it in a test.

End-to-end: the `pi_config` fixture names no endpoint, so existing tests make no curator
call. A test of memory builds a pi config pointing at `fake_endpoint` (Phase 1), runs the
two-phase `DESIGN`, and checks that phase 1's commit holds `docs/memory.md` with the fake's
answer, that phase 2's prompt file holds it in its `<memory>` block, and that a fake reply
with status 500 twice leaves the memory as it was and the run committed.

**Where**
- `styre/runner.py:487-500` `commit_phase`; `:324` and `:365` the two `build_prompt` calls;
  `styre/gitops.py:32-45` `stage_all`, `staged_diff`, `has_staged_changes`, `commit`.
- `styre/rundir.py` `RunDir.notes(n)`: the phase's collected `notes-next.md`.
- `styre/prompts.py:26-71` `build_prompt`; 74-127 `planner_prompt`; 136-187
  `advisor_prompt` (its rules end at 184).
- `styre/cli.py:162` `cmd_check`'s prompt sizes.
- `styre/summarize.py:174-222` `Phase`, 252-300 `read_timeline`, 567-601
  `model_call_lines`, 603-666 `where_to_look`.
- `tests/conftest.py:80-118` the `pi_config` and `styre` fixtures;
  `tests/test_run_end_to_end.py` for the run tests.

### Exit criteria
- A green phase's commit holds the curator's new `docs/memory.md` when styre's pi config names an endpoint.
- A phase with no staged diff is not committed, whatever the curator returns.
- With no endpoint in the pi config, no curator call is made and no `memory` event is written.
- A failed curator call leaves `docs/memory.md` unchanged, commits the phase, and shows `memory unchanged` in `summary.md`.
- Every builder prompt has the `<memory>` block, and `planner_prompt` and `advisor_prompt` name `docs/memory.md`.
- An end-to-end test covers each of the four bullets above, and every existing test still passes.

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 3: The reviewer's call and its proof

Add `styre/reviewer.py`: the review schema, the reviewer's call with one retry, the checks on
its answer, the proof of each finding on the tree, and the fix phase built from the proven
ones. Nothing calls it yet; the runner does in Phase 4.

```python
MAX_FINDINGS = 5
READ_TOOLS = ["Read", "Grep", "Glob"]
REVIEW_SCHEMA = {...}

@dataclass
class Finding:
    title: str
    where: str          # file:line
    why: str
    test_path: str = "" # all three empty: no test
    test: str = ""
    command: str = ""
    proven: bool = False

def check(answer, root) -> tuple[list[Finding] | None, list[str]]
def review(design_path, base, last_phase, *, cwd, timeline, log_dir) -> tuple[list[Finding] | None, str | None]
def prove(findings, *, root, log, gate_timeout, timeline) -> list[Finding]
def fix_phase(proven, last_phase, n) -> Phase
```

- `REVIEW_SCHEMA`: an object with `findings`, an array of at most `MAX_FINDINGS` objects,
  each with the string fields `title`, `where`, `why`, `test_path`, `test`, `command`, all
  required, no others. An empty string means no test.
- `check(answer, root)` returns `(findings, [])`, or `(None, problems)` with one sentence
  per broken rule: `answer` has no `findings` list; more than `MAX_FINDINGS`; a blank
  `title`, `where` or `why`; some but not all of `test_path`, `test` and `command` set; a
  `test_path` that is absolute, leaves the repository (`..`), repeats another finding's, or
  already exists under `root`; a `test` that `styre.guard.SKIP_RE` matches.
- `review(...)` calls `claude.call("reviewer", reviewer_prompt(...), REVIEW_SCHEMA,
  READ_TOOLS, cwd=cwd, timeline=timeline, log_dir=log_dir)`. A call error returns
  `(None, error)`. An answer `check` refuses gets one retry with `Your review was refused:`
  and the problems; a second refusal returns `(None, problems[0])`.
- `prove(findings, ...)`: for each finding with a test, write the file under `root`
  (parents created), then run its `command` with `styre.process.run(command, shell=True,
  timeout=gate_timeout, log=log)`. A non-zero exit sets `proven=True`. An exit of 0 deletes
  the file again: the test passes, so the finding is not proven. Write one `finding` timeline
  event per finding with `title`, `where`, `why`, `test_path`, `proven`, and `rc` when a
  command ran. Return all findings.
- `fix_phase(proven, last_phase, n)` returns a `styre.design.Phase` with the title
  `Phase {n}: Review fixes`, a body that lists each proven finding (title, where, why, its
  test path and command) and says to make the tests pass without editing them, the criteria
  `Each review test passes: \`<command>\`` per finding, the gate `last_phase.gate` followed by
  each finding's command, and `acceptance` the findings' `(test_path, test)` pairs, so styre
  restores them before every gate as it does acceptance tests.

Add `reviewer_prompt(design_path, base, last_phase)` to `styre/prompts.py`. It says: a local
model built the design at `design_path` unattended, and every phase is committed; review the
commits since `base` (`git log --oneline {base}..HEAD` and `git diff {base}..HEAD` show them;
read the files with Read, Grep and Glob, which cannot run git, so the prompt includes the
output of both `git log --oneline` and `git diff --stat` for that range); `docs/memory.md`,
when it exists, holds facts earlier phases learned; name at most 5 findings, most severe
first: behaviour the design states that the code gets wrong, a crash, a rule broken, never
style; for each, where (file:line) and why in one paragraph; when it can be tested, a new test
file in the repository's framework and conventions, placed where this gate collects it:
`last_phase.gate`, with a command that runs only that file, fails on the code as it is, and
passes once the bug is fixed; no skip or xfail marker; an empty `findings` list when there is
nothing.

**Where**
- `styre/advisor.py:1-131`: a module of the same kind (a schema, `check` returning
  sentences, a call with one retry); copy its shape.
- `styre/claude.py:50` `call(role, prompt, schema, tools, *, cwd, timeline, log_dir,
  timeout=None) -> ClaudeResult`.
- `styre/design.py:95-108` `Phase` (`title`, `body`, `criteria`, `gate`, `acceptance`) and
  160-182 `validate`, whose path rules for acceptance tests `check` mirrors.
- `styre/guard.py:14` `SKIP_RE`.
- `styre/process.py:265-284` `run(cmd, timeout=None, log=None, shell=False) -> (rc, out)`.
- `styre/gitops.py:8-11` `git(*args) -> (rc, out)` for the log and the diff stat.
- `styre/prompts.py:136-187` `advisor_prompt`: the style. Add `reviewer_prompt` after it.
- `tests/test_advisor.py`: tests of the same kind against `tests/fake_claude.py`.
- New: `styre/reviewer.py`, `tests/test_reviewer.py`.

Do not change `styre/runner.py` in this phase.

### Exit criteria
- `styre/reviewer.py` defines `MAX_FINDINGS`, `READ_TOOLS`, `REVIEW_SCHEMA`, `Finding`, `check`, `review`, `prove` and `fix_phase` as above.
- `styre/prompts.py` defines `reviewer_prompt(design_path, base, last_phase)`, which holds the range's `git log --oneline` and `git diff --stat`.
- `prove` keeps a failing test's file and marks it proven, and deletes a passing test's file.
- `tests/test_reviewer.py` covers each sentence `check` returns, `review`'s good answer, retry and failed call, `prove` both ways, and `fix_phase`'s title, gate and acceptance.
- Nothing outside `styre/reviewer.py`, `styre/prompts.py` and `tests/` is edited.

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 4: Review in the run

After the last design phase commits, review the run, prove the findings, and run one fix
phase for the proven ones.

1. `orchestrate` (`styre/runner.py:536-635`) records `base = head_sha()` before the first
   phase runs. With `--from-phase`, the review then covers this invocation's phases only.
2. Move the body of the phase loop, from `run_phase(ctx, n)` through the amend branch, into
   one function `run_with_advice(ctx, n, patches) -> tuple[int, str | None, int]` returning
   the phases committed, the stop message or None, and the patch count. The loop calls it;
   behaviour does not change.
3. When the loop ends with no stop: `findings, error = reviewer.review(ctx.design_path, base,
   ctx.phases[-1], cwd=Path.cwd(), timeline=tl, log_dir=run.root / "logs")`. A failed call
   writes a `review` event with `error` and ends the run with its exit code unchanged. Else
   `reviewer.prove(...)` with `root=Path.cwd()`, `log=run.root / "logs" / "review.log"` and
   `opts.gate_timeout`, then a `review` event with `findings` and `proven`, the counts.
4. With proven findings: `fix = reviewer.fix_phase(proven, ctx.phases[-1],
   len(ctx.phases) + 1)`, append it to `ctx.phases` (this run only; the design file is not
   changed), and run it with `run_with_advice`: it is built, gated, curated, committed and
   advised like any phase. Its stop is the run's stop. There is no second review.
5. With no proven findings: delete nothing more (`prove` already removed passing tests), and
   the run ends.

`summarize` gets a `## Review` section after "Model calls", from the `review` and `finding`
events: `No findings.`, or one line per finding, `- proven, fixed in Phase 6: <title>
(<where>)` (the fix phase's number from its `phase_end`), `- proven, not fixed: <title>`
when the fix phase stopped, `- not proven: <title>` for a test that passed, `- reported:
<title> (<where>): <why>` for one without a test; or `The review could not be made:
<error>`. A run with no `review` event has no section.

End-to-end tests, each with `tests/fake_claude.py` replies:
- no findings: the run commits its phases and `summary.md` says `No findings.`;
- one finding whose command is `test -f fixed.txt` (fails on the tree): a fix phase
  `Phase 3: Review fixes` runs, the fake pi writes `fixed.txt`, and it commits;
- one finding whose command is `test -f done.txt` (passes): no fix phase, the test file is
  gone, `not proven` in `summary.md`;
- a failed review call: exit code 0, every design phase committed, the error in
  `summary.md`.

**Where**
- `styre/runner.py:536-635` `orchestrate`, its loop at 547-626 and `run_end` at 628;
  `styre/gitops.py` `head_sha`.
- `styre/reviewer.py` from Phase 3.
- `styre/summarize.py:224-240` `Run` (add the review fields), 252-300 `read_timeline`,
  668-679 `render`.
- `tests/fake_pi.py` actions (`ok` writes `done.txt`); the `plan` argument of the `styre`
  fixture maps a prompt file name such as `phase3.prompt.md` to an action. Add an action
  that writes `fixed.txt` if none fits.
- `tests/test_m4_amend_stop.py`: helpers that build `fake_claude` replies and read the
  timeline.

### Exit criteria
- A run whose design phases all commit is reviewed once, with the range from the commit it started on.
- Proven findings get one fix phase, numbered after the last design phase, gated by the last gate plus their commands, committed when green.
- A finding whose test passes on the tree gets no fix phase, and its test file is removed.
- A failed review call does not change the run's exit code.
- `summary.md` has the `## Review` section as above.
- An end-to-end test covers each of the four cases above, and every existing test still passes.

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```

## Phase 5: Docs

Describe the reviewer and memory where a reader of styre looks for how a run works. Docs
only.

- `CLAUDE.md`: add `styre/local.py`, `styre/curator.py` and `styre/reviewer.py` to the Files
  table. In "What happens per phase", step 7: before the commit, the curator updates
  `docs/memory.md`. After the last phase: the review and the fix phase. In "State on disk",
  add `docs/memory.md` beside `docs/decisions.md`. Under "Decisions that are settled", the
  bullet "Until a role exists, its judgement is the director's": the reviewer now reviews a
  finished run.
- `docs/architecture.md`: add the three modules to the module table (lines 49-66). After the
  "One phase" flowchart, add a short paragraph on the curator before each commit and the
  review after the last phase.
- `skills/styre/DIRECTOR.md` rule 4: the run's own review comes first; the director reads
  its section in `summary.md`, then reviews what it did not cover.
- `skills/styre/SKILL.md` step 4, "Done": read the review section first.
- `README.md` line 19: the reviewer is built.

### Exit criteria
- Each file in the list above says what its bullet asks, and no other file is edited.
- No doc names Claude, Anthropic or Claude Code as the author of a commit.

### Gate
```
uv run --with pytest python -m pytest -q
uvx ruff check .
```
