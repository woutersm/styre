# styre

Hand a phased design to a local coding model, leave it running, and come back to one git
commit per phase, each one passed by your own tests.

You write a design document split into phases. Each phase says what to build, what must be
true when it is done, and which commands prove it: the **gate**. styre gives each phase to a
fresh [pi](https://www.npmjs.com/package/@earendil-works/pi-coding-agent) process, then runs
the gate itself and inspects the staged diff. The agent saying it is done counts for nothing:
a phase is committed only when the gate is green and no test was skipped or deleted. A red
gate goes back to the agent as a fix round, a limited number of times, and then the run stops
with the work uncommitted.

> **Status: alpha.** Used on macOS with local 27B models served over an OpenAI-compatible
> API. Checked against pi 1.0.4: the event stream and the agent tools. Expect rough edges
> anywhere else.

## Built for agents

Almost nothing in styre is read by a person while it runs. It has three readers, and each
one got an interface designed for it.

**The builder**, a local model inside pi, gets:

- **A tool API with the guardrails in it.** `styre_gate` runs exactly the commands styre will
  run afterwards and returns pass/fail per command with the tail of each failure, as data.
  `styre_progress` takes four fields (`done`, `now`, `next`, `learned`) instead of free
  prose. `styre_finish` **refuses `DONE` unless the last `styre_gate` passed**, and counts
  the agent's self-fix rounds from the recorded gate runs instead of asking for them.
- **Docs written for a machine.** A managed block in the target repo's `AGENTS.md`, which pi
  loads into every request: what is checked after it stops and why reporting success early
  gains nothing, which files to write and who reads each one, and how to read narrowly. Only
  standing rules go there; each phase's prompt carries only that phase.
- **A context budget it cannot overspend.** pi extensions cap what a `read` or a `bash` call
  puts into context, drop earlier thinking from every request, and cancel compaction. Past
  75% of the model's window, styre stops the agent between two turns, has it write its
  progress file, and continues in a fresh process from that file.

**The director**, an interactive assistant such as Claude Code, works the loop around styre:
writing the design with the owner, starting and resuming runs, reading a stop, reviewing the
result. [`skill/`](https://github.com/woutersm/styre/tree/main/skill) is a Claude Code skill
for that job, with rules for what it may do without asking.

**The gate** reads no agent's account at all. styre runs the gate commands itself, rejects a
diff that adds skip/xfail markers or loses test functions, and builds the run's report,
`summary.md`, from its own measured timeline rather than from anything the agent wrote.

## What broke, and what styre does about it

Every mechanism above exists because a real run failed without it. Some of the measurements:

| What happened | What styre does now |
| --- | --- |
| My own interactive pi setup (web tools, a personal `AGENTS.md`) was **47% of every request**. | pi runs under styre's own config directory, and `run` refuses to start without it. Fixed overhead went from 8,331 to 1,639 tokens. |
| Tool results were **67% of a 60k-token phase**, with single reads of 18,000 characters. | `cap-output.js`: a `read` returns at most 300 lines, a `bash` call its first 60 and last 90, with a note on how to get the rest. |
| Compaction re-prefilled 48k tokens (**8.5 minutes**); on a server without a thinking budget it failed 16 times in one phase. | Compaction is cancelled. A full step is restarted from its progress file instead. |
| A restarted agent had never written its progress file, and spent **80 minutes** re-reading the tree. | Before a restart, the stopped step gets one extra turn in its own cached session, whose only job is to write the file. |
| The provider dropped a request and returned an empty stream. styre reported "no state file written", and **two days** went into reading the agent's contract. | An all-zero usage block stops the phase with "the model returned an empty response". |
| A design told the agent to skip a test on non-macOS; it did, and the test guard rejected the phase. | `styre check` flags a design that asks for a skip marker before the run starts. |
| A phase named a new library with no example, so every step spent ~12 `python -c` calls learning its API; **80% of the phase's output was thinking**. | `styre check` flags a new dependency with no code snippet; [`skill/writing-designs.md`](https://github.com/woutersm/styre/blob/main/skill/writing-designs.md) says what a phase must hand over. |

[`CLAUDE.md`](https://github.com/woutersm/styre/blob/main/CLAUDE.md) is the full design record:
how it works, what was measured, and which decisions are settled.

## Requirements

- Python 3.9+ (stdlib only, no dependencies)
- git, and a target repository with a clean working tree
- [pi](https://www.npmjs.com/package/@earendil-works/pi-coding-agent) on `PATH`, with a model it can use
- Node.js (pi needs it anyway)

## Install

```sh
uv tool install styre          # or: pipx install styre
```

From source: `uv tool install git+https://github.com/woutersm/styre`.

## Give pi a config of its own

styre runs pi with `PI_CODING_AGENT_DIR=~/.config/pi/styre` and refuses to start without it.
An unattended run should not inherit your interactive setup: on one machine the operator's
extensions and personal `AGENTS.md` were 47% of every request.

It needs two files. `models.json` names your model host and model; this one is a local
OpenAI-compatible server:

```json
{
  "providers": {
    "local": {
      "baseUrl": "http://localhost:8000/v1",
      "api": "openai-completions",
      "apiKey": "none",
      "models": [
        { "id": "my-model", "reasoning": true, "input": ["text"], "contextWindow": 120000 }
      ]
    }
  }
}
```

`settings.json` pins that model, and installs no packages:

```json
{ "defaultProvider": "local", "defaultModel": "my-model", "packages": [] }
```

```sh
mkdir -p ~/.config/pi/styre      # then write the two files above into it
```

A hosted provider works the same way: copy `models.json` and `auth.json` from your own pi
config (`~/.pi/agent/` by default) and pin the model in `settings.json`. Keep the directory
lean: no `AGENTS.md`, no extensions. `contextWindow` matters: styre restarts a phase in a
fresh process at 75% of it, and without it that restart is off. `styre run` refuses to
start without `models.json`.

## Quick start

From the **root** of the repository you want built:

```sh
styre check docs/my-design.md    # validate; print phases, gates, prompt sizes and warnings
styre run docs/my-design.md      # run every phase, one commit each
```

Afterwards:

```sh
styre summarize                  # what happened: per phase time, context, fix rounds, where to look
git log --oneline styre/my-design
```

A stopped run resumes with `styre run docs/my-design.md --from-phase N`.

## The design file

Any preamble, then one block per phase:

````markdown
## Phase 1: The data and the API

What to build, where, and the exact shapes of anything external.

### Exit criteria
- a statement the agent must make true, checkable in the diff or the tests

### Gate
```
uv run ruff check .
uv run pytest -q
```
````

A phase with no criteria list or no gate block is an error. Each phase's prompt carries the
preamble, the list of phase titles, and **only its own section**. Earlier phases reach it
through the working tree and a short note the previous phase leaves behind.

How to cut a design so it runs well (size a phase by its work, keep each gate green on its
own phase's work, give a new library's API in the phase that uses it) is in
[`skill/writing-designs.md`](https://github.com/woutersm/styre/blob/main/skill/writing-designs.md). [`example-design.md`](https://github.com/woutersm/styre/blob/main/example-design.md) is a small
two-phase example.

## What a phase goes through

1. styre writes its rules into the target repo's `AGENTS.md`, between
   `<!-- styre:begin -->` markers. Your own text in that file is kept.
2. A fresh pi process gets the phase's prompt. The agent works in the repo and has three
   tools of styre's:
   - `styre_gate` runs the phase's gate and returns what failed
   - `styre_progress` keeps a progress file a restarted process can continue from
   - `styre_finish` records DONE or BLOCKED; it refuses DONE until the gate is green
3. When the agent's context passes 75% of the model's window, styre stops it between two turns
   and continues in a fresh process from the progress file.
4. styre runs every gate command itself and checks the staged diff for new skip/xfail markers
   or removed tests.
5. On a failure, the agent gets a fix round with the whole failure, up to `--retries` (default 2).
6. All green: one commit, titled after the phase. Otherwise the run stops and leaves the work
   uncommitted.

## What it writes into your repository

| What | Where |
| --- | --- |
| A branch | `styre/<design name>` (`--branch` to choose) |
| One commit per phase | on that branch |
| The rules block | `AGENTS.md`, between styre's markers |
| The agent's decision log | `docs/decisions.md`, append-only, committed; no later phase reads it |
| Run records | `.styre/runs/<id>/`: prompts, logs, pi's event stream, `timeline.jsonl`, `summary.md` |

`.styre/` and common caches are added to `.git/info/exclude`, so nothing of styre's is
committed except `AGENTS.md` and the agent's own work.

## Commands

| Command | |
| --- | --- |
| `styre check <design>` | Validate, print each phase's gate and prompt size, and warn about shapes that fail |
| `styre run <design>` | Run it. `--from-phase N` resumes, `--retries`, `--timeout` (seconds of *silence*, default 7200), `--gate-timeout`, `--branch`, `--quiet`; `--help` for all |
| `styre summarize [run]` | The report for the latest run, or a named one |

## Directing it

styre makes no judgement calls: it runs, gates and commits. Writing the design, deciding what
a stopped phase needs, and reviewing the result are for whoever directs the run: a person, or
a person with an interactive assistant. [`skill/DIRECTOR.md`](https://github.com/woutersm/styre/blob/main/skill/DIRECTOR.md)
is five rules for that; [`skill/writing-designs.md`](https://github.com/woutersm/styre/blob/main/skill/writing-designs.md)
is how to shape a design so a local model can finish it.

To use [`skill/`](https://github.com/woutersm/styre/tree/main/skill) as a [Claude Code](https://claude.com/claude-code)
skill, link it in once and `/styre` works in every repository:

```sh
ln -s "$(pwd)/skill" ~/.claude/skills/styre    # from a clone of this repository
```

## Safety

pi has no sandbox and runs commands without asking. Run it in an ordinary clone of
the target repository, with only the credentials the job needs. styre bounds time (an idle
timeout per step, a timeout per gate command) but not spend: set a limit with your model
provider.

## Development

```sh
uv run --with pytest python -m pytest -q     # the suite; the end-to-end tests drive a fake pi
uvx ruff check .
```

`tests/fake_pi.py` stands in for pi, so the whole loop runs without a model. [`CLAUDE.md`](https://github.com/woutersm/styre/blob/main/CLAUDE.md) is the design record: how it works, what was
measured, and which decisions are settled. [`TODO.md`](https://github.com/woutersm/styre/blob/main/TODO.md) is what is open.

## License

MIT, see [LICENSE](https://github.com/woutersm/styre/blob/main/LICENSE).
