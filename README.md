# styre

[![test](https://github.com/woutersm/styre/actions/workflows/test.yml/badge.svg)](https://github.com/woutersm/styre/actions/workflows/test.yml)

styre builds a phased design with a local coding model while nobody watches. Each phase ends
in one git commit, and a phase is committed only when your own tests pass.

You write a design document split into phases. Each phase says what to build, what must be
true when it is done, and which commands prove it. Those commands are the gate. styre gives
each phase to a fresh [pi](https://www.npmjs.com/package/@earendil-works/pi-coding-agent)
process. When the agent stops, styre runs the gate itself and inspects the staged diff. It
ignores the agent's claim that the work is done. A phase is committed only when the gate
passes and the diff neither skips nor deletes a test. A failing gate goes back to the agent as
a fix round. After `--retries` rounds the run stops and leaves the work uncommitted.

> Status: alpha. Used on macOS with local 27B models behind an OpenAI-compatible API, and
> checked against the event stream and agent tools of pi 1.0.4. Other setups are untested.

## Who reads what styre writes

No person reads anything styre writes while a run is going. Two agents and styre's own gate
do, and each has an interface made for it.

### The builder

The builder is the local model inside pi. It gets tools, instructions and a context budget.

**Tools that enforce the rules.** `styre_gate` runs the same commands styre will run
afterwards and returns pass or fail per command, with the tail of each failure. `styre_progress`
takes four fields, `done`, `now`, `next` and `learned`, instead of free prose. `styre_finish`
refuses `DONE` unless the last `styre_gate` call passed. It counts the agent's own fix rounds
from the recorded gate runs instead of asking the agent.

**Instructions written for a model.** styre keeps a block in the target repository's
`AGENTS.md`, which pi loads into every request. The block says what styre checks after the
agent stops, why claiming success early gains nothing, which files to write and who reads each
one, and how to read a large file in parts. It holds only the rules that apply to every phase.
Each phase's prompt holds only that phase.

**A context budget.** styre's pi extensions cap what a `read` or `bash` call adds to the
context, drop earlier thinking from every request, and cancel pi's compaction. When the
context passes 75% of the model's window, styre stops the agent between two turns, has it
write its progress file, and continues the phase in a fresh process from that file.

### The director

The director is an interactive assistant such as Claude Code. It writes the design with the
owner, starts and resumes runs, decides what a stopped phase needs, and reviews the result.
[`skills/`](https://github.com/woutersm/styre/tree/main/skills) has two Claude Code skills for
that job: `/styre-design` writes a design with the owner, and `/styre` runs the rest. They list
what the director may do without asking.

### The gate

The gate never reads anything the agent wrote. styre runs the gate commands itself and rejects
a diff that adds skip or xfail markers or removes test functions. It writes the run's report,
`summary.md`, from its own timeline of measured events.

## What broke, and what styre does about it

[`docs/lessons.md`](docs/lessons.md) lists the failures from real runs that shaped styre,
with what it does about each. [`docs/architecture.md`](docs/architecture.md) shows how the
parts fit, with diagrams.

[`evals/`](https://github.com/woutersm/styre/tree/main/evals) tests these interfaces against a
real model and against run history. The first eval checks whether the builder keeps the
contract its tools and instructions describe. On a local 27B model it did in 30 of 30 trials.
In one scenario the gate could not pass honestly, and the agent finished BLOCKED in every trial
instead of faking a pass. The second eval scores `styre check`'s warnings against the phases
that went badly in one real project.

## Requirements

- Python 3.9 or later, standard library only
- git, and a target repository with a clean working tree
- [pi](https://www.npmjs.com/package/@earendil-works/pi-coding-agent) on `PATH`, with a model it can use
- Node.js, which pi needs anyway

## Install

```sh
uv tool install git+https://github.com/woutersm/styre
# or: pipx install git+https://github.com/woutersm/styre
```

## Give pi its own config

styre runs pi with `PI_CODING_AGENT_DIR=~/.config/pi/styre` and refuses to start without it.
An unattended run should not inherit your interactive setup. On my machine, my own extensions
and personal `AGENTS.md` were 47% of every request.

The directory needs two files. `models.json` names the model host and the model. This one
points at a local OpenAI-compatible server:

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

`settings.json` selects that model and installs no packages:

```json
{ "defaultProvider": "local", "defaultModel": "my-model", "packages": [] }
```

```sh
mkdir -p ~/.config/pi/styre      # then write the two files above into it
```

For a hosted provider, copy `models.json` and `auth.json` from your own pi config, which is
`~/.pi/agent/` by default, and select the model in `settings.json`. Leave out `AGENTS.md` and
extensions. Set `contextWindow`. styre moves a step to a fresh process at 75% of it, and
without it styre never does.

## Quick start

Write the design with Claude Code: run `styre design "what to build"`, or type `/styre-design`
in Claude Code, in the repository you want built (see [Using it with Claude Code](#using-it-with-claude-code)), or write it by hand in the
format below. Then, from the root of that repository:

```sh
styre check docs/my-design.md    # validate; print phases, gates, prompt sizes and warnings
styre run docs/my-design.md      # run every phase, one commit each
```

After the run:

```sh
styre summarize                  # per phase: time, context, fix rounds, what to look at
git log --oneline styre/my-design
```

To resume a stopped run, use `styre run docs/my-design.md --from-phase N`.

## The design file

A design starts with an optional preamble that every phase sees, such as the project's
goal and conventions. Then comes one section per phase, in this shape:

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

A phase without a criteria list or a gate block is an error. Each phase's prompt holds the
preamble, the list of phase titles and only that phase's section. The agent learns about
earlier phases from the working tree and from a short note the previous phase leaves.

[`skills/styre/writing-designs.md`](https://github.com/woutersm/styre/blob/main/skills/styre/writing-designs.md)
explains how to cut a design so a local model can finish it. It covers how big a phase should
be, how to keep each gate passing on its own phase's work, and where to show the API of a new
library. [`example-design.md`](https://github.com/woutersm/styre/blob/main/example-design.md) is
a small two-phase example.

## What happens in a phase

1. styre writes its rules into the target repository's `AGENTS.md`, between
   `<!-- styre:begin -->` markers. It keeps your own text in that file.
2. A fresh pi process gets the phase's prompt. The agent works in the repository and has three
   styre tools:
   - `styre_gate` runs the phase's gate and returns what failed
   - `styre_progress` keeps a progress file that a fresh process can continue from
   - `styre_finish` records DONE or BLOCKED, and refuses DONE until the gate passes
3. When the agent's context passes 75% of the model's window, styre stops it between two turns
   and continues in a fresh process from the progress file.
4. styre runs every gate command itself and checks the staged diff for new skip or xfail
   markers and for removed tests.
5. On a failure, the agent gets a fix round with the whole failure, up to `--retries` times.
   The default is 2.
6. If everything passes, styre makes one commit titled after the phase. Otherwise the run stops
   and leaves the work uncommitted.

## What it writes into your repository

| What | Where |
| --- | --- |
| A branch | `styre/<design name>`, or the one `--branch` names |
| One commit per phase | on that branch |
| The rules block | `AGENTS.md`, between styre's markers |
| The agent's decision log | `docs/decisions.md`, append-only and committed. No later phase reads it. |
| Run records | `.styre/runs/<id>/`, with prompts, logs, pi's event stream, `timeline.jsonl` and `summary.md` |

styre adds `.styre/` and common caches to `.git/info/exclude`. The only file of its own that it
commits is `AGENTS.md`.

## Commands

| Command | What it does |
| --- | --- |
| `styre design [idea]` | Opens interactive Claude Code on `/styre-design` in this repository. A launcher: you do the interview and approve the design; styre calls no model |
| `styre check <design>` | Validates the design, prints each phase's gate and prompt size, and warns about designs that tend to fail |
| `styre run <design>` | Runs it. Options include `--from-phase N` to resume, `--retries`, `--timeout` in seconds of silence with a default of 7200, `--gate-timeout`, `--branch` and `--quiet`. `--help` lists them all. |
| `styre summarize [run]` | Prints the report for the latest run, or for the one named |

## Using it with Claude Code

styre makes no judgement calls. It runs phases, runs gates and commits. The person directing
the run, alone or with an interactive assistant, writes the design, decides what a stopped
phase needs and reviews the result.
[`skills/styre/DIRECTOR.md`](https://github.com/woutersm/styre/blob/main/skills/styre/DIRECTOR.md) gives five
rules for that work.

[`skills/`](https://github.com/woutersm/styre/tree/main/skills) holds two
[Claude Code](https://claude.com/claude-code) skills:

- `/styre-design` writes a design with you. It asks what you want built, reads the
  repository, proposes the phases, writes `docs/<name>-design.md` and runs `styre check` on it.
- `/styre` runs the whole loop: design, run, read a stop, resume, and review the result.

Link them once, from a clone of this repository, and both work in every repository:

```sh
ln -s "$(pwd)"/skills/* ~/.claude/skills/
```

## Safety

pi has no sandbox and runs commands without asking. Run it in an ordinary clone of the target
repository, with only the credentials the job needs. styre limits time, with an idle timeout
per step and a timeout per gate command. It does not limit spending, so set a limit with your
model provider.

## Development

```sh
uv run --with pytest python -m pytest -q     # the suite; the end-to-end tests use a fake pi
uvx ruff check .
```

`tests/fake_pi.py` stands in for pi, so the whole loop runs without a model.
[`CLAUDE.md`](https://github.com/woutersm/styre/blob/main/CLAUDE.md) records the design: how it
works, what was measured, and which decisions are settled.
[`TODO.md`](https://github.com/woutersm/styre/blob/main/TODO.md) lists what is open.

## License

MIT, see [LICENSE](https://github.com/woutersm/styre/blob/main/LICENSE).
