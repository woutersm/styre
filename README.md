# styre

[![test](https://github.com/woutersm/styre/actions/workflows/test.yml/badge.svg)](https://github.com/woutersm/styre/actions/workflows/test.yml)

styre runs a phased design through the [pi](https://www.npmjs.com/package/@earendil-works/pi-coding-agent)
coding agent while nobody watches. Each phase ends in one git commit, and styre commits a
phase only when your own tests pass. It is built for local models, which cost nothing per
token but are slow. styre runs the gate itself and never takes the agent's word that a
phase is done.

> Status: alpha. Used on macOS with local 27B models behind an OpenAI-compatible API, and
> checked against the event stream and agent tools of pi 1.0.4. Other setups are untested.

## v2

styre v2 orchestrates a local coding agent with Claude Code as planner, advisor and
reviewer. styre commits a phase only when its gate passes: your build, lint and tests.

> v2 is in progress. The planner (`styre plan`) and the advisor are built; the reviewer is
> not. Reference setup: Qwen3.8-27B through pi, and Claude Code on Opus 5.5. The plan and
> its milestones are in [`docs/v2.md`](docs/v2.md).

## What it is

styre is a command-line program written in Python. It is not a pi extension and not a Claude
Code plugin. It starts pi itself, once per phase, as a separate process, and stays outside it,
so whether a phase passed never depends on what the agent says. You install nothing into pi.

It has three parts:

| Part | What it is | Install |
| --- | --- | --- |
| `styre` | The program. It runs the phases, runs the gate and commits. | `uv tool install`, see [Install](#install) |
| [`styre/pi_extensions/`](https://github.com/woutersm/styre/tree/main/styre/pi_extensions) | Four pi extensions: the agent's `styre_*` tools and the limits on its context | Nothing. styre passes them to every pi process it starts. |
| [`skills/`](https://github.com/woutersm/styre/tree/main/skills) | Three Claude Code skills, for writing a design, simplifying it and directing runs | Optional, see [Using it with Claude Code](#using-it-with-claude-code) |

## Why use it

You can already run `pi -p "build this"` on a large task. On a local model, a run of several
hours fails in a few known ways. styre was built to handle each of them:

| Running the agent on its own | Running it under styre |
| --- | --- |
| The agent says the tests pass. Sometimes they do not. | styre runs your gate commands itself after the agent stops, and commits nothing on a failing gate. |
| An agent stuck on a failing test can skip or delete it to get a green run. | styre rejects a diff that adds skip or xfail markers or removes test functions. |
| One long session keeps every file read, command output and earlier thought. On a local host every request gets slower. | Each phase starts a fresh process with only that phase's prompt. styre caps tool output, drops earlier thinking, and at 75% of the model's window continues the step in a fresh process from a progress file. |
| pi's compaction prefills the whole context again. One compaction took 8.5 minutes. | styre cancels compaction. |
| A hung command stalls the run. A model host that refuses a request looks like an agent ignoring its instructions. | An idle timeout kills the whole process group. An empty response stops the phase with "the model returned an empty response". |
| At the end you have one large diff. | You have one commit per phase on its own branch, each a point to roll back to, and a report of what each phase took. |

The work splits in two. You write the design, start the run, decide what a stopped phase
needs and review the result, alone or with an interactive assistant such as Claude Code.
styre does only the parts that need no judgement, with one exception: `styre plan` asks
Claude, through `claude -p`, to add implementation help to a design before a run, and you
review that commit. Otherwise styre calls no model of its own and makes no network request.

Each mechanism above came from a failed run. Most came from one project built over 44 phases
with a local 27B model, and [`docs/lessons.md`](docs/lessons.md) lists each failure with its
numbers. In [`evals/`](https://github.com/woutersm/styre/tree/main/evals), a local 27B model
kept the contract styre's tools and instructions describe in 30 of 30 trials. In one scenario
the gate could not pass honestly, and the agent finished BLOCKED in every trial instead of
faking a pass.

styre is a poor fit when you want to watch and steer each step, or when the project has no
tests or checks to gate on. styre can only be as strict as the gate you give it.

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
styre plan docs/my-design.md     # ask Claude to add implementation help; one commit, you review it
styre check docs/my-design.md    # validate; print phases, gates, prompt sizes and warnings
styre run docs/my-design.md      # run every phase, one commit each
```

## `styre plan` — the design Claude completes for a local model

A design written by a frontier model tells the phases what to build, but a local model building
unattended also needs the help a frontier model would not bother writing: which files and lines
the phase touches, the signatures it calls, what to copy from, the traps. `styre plan
<design.md>` sends the design to `claude -p` with read-only tools (Read, Grep, Glob), asks it to
return the whole design with that help added, and then styre checks the answer itself: it still
validates, the phases, their titles, gates and exit criteria are unchanged, every line of the
brief is still there (the help is additive only), and no phase prompt is over 40,000
characters. An answer that drops or edits the brief is sent back once with the list of what broke; still broken, and the command
exits 1 with the brief untouched.

A good answer replaces the design file and becomes one commit, `Plan: <design name>`, on your
current branch. The command prints the design's remaining warnings and the planner's tokens in
and out. Read it with `git show` and, when you agree, `styre run <design.md>` runs it exactly
as it runs any design.

After the run:

```sh
styre summarize                  # per phase: time, context, fix rounds, what to look at
git log --oneline styre/my-design
```

To resume a stopped run, use `styre run docs/my-design.md --from-phase N`.

## Acceptance tests

An **acceptance test** is a test in a phase's section of the design, for an interface the
brief names or a rule it states. `styre plan` writes them per phase: one test file per
named interface and stated rule, in the phase's `### Acceptance tests` section. You review
them with the plan, in the same commit.

At the start of each phase styre writes those files into the working tree, and writes them
back before every gate run: a builder that edits or deletes one is undone, and the report
names the file. A builder that finds one of them wrong does not fix it; it reports `BLOCKED` and the
fix is a change to the design.

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
See [Using it with Claude Code](#using-it-with-claude-code).

### The gate

The gate never reads anything the agent wrote. styre runs the gate commands itself and rejects
a diff that adds skip or xfail markers or removes test functions. It writes the run's report,
`summary.md`, from its own timeline of measured events.

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
| `styre design [idea]` | Opens interactive Claude Code on `/styre-design` in this repository. A launcher: you do the interview and approve the design; styre reads nothing back from it |
| `styre check <design>` | Validates the design, prints each phase's gate and prompt size, and warns about designs that tend to fail |
| `styre plan <design>` | Asks Claude to add the implementation help a local model needs, checks the answer kept the brief intact, and commits it (`Plan: <name>`) |
| `styre run <design>` | Runs it. Options include `--from-phase N` to resume, `--retries`, `--timeout` in seconds of silence with a default of 7200, `--gate-timeout`, `--branch` and `--quiet`. `--help` lists them all. |
| `styre summarize [run]` | Prints the report for the latest run, or for the one named |

## Using it with Claude Code

Apart from `styre plan`, styre makes no judgement calls. It runs phases, runs gates and commits. The person directing
the run, alone or with an interactive assistant, writes the design, decides what a stopped
phase needs and reviews the result.
[`skills/styre/DIRECTOR.md`](https://github.com/woutersm/styre/blob/main/skills/styre/DIRECTOR.md) gives five
rules for that work.

[`skills/`](https://github.com/woutersm/styre/tree/main/skills) holds three
[Claude Code](https://claude.com/claude-code) skills:

- `/styre-design` writes a design with you, and `styre design "idea"` opens it. It grills you
  in rounds of questions and writes the answers down as it goes: the project's terms in
  `GLOSSARY.md`, and each hard trade-off as a short decision record in `docs/adr/`. It then
  reads the repository, cuts the phases, writes `docs/<name>-design.md` from those docs, runs
  `/styre-simplify` on it and `styre check`.
- `/styre-simplify` challenges a design for the cuts that remove most work for least value,
  and puts each one to you. `styre simplify docs/<name>-design.md` opens it on an existing
  design.
- `/styre` runs the whole loop: design, run, read a stop, resume, and review the result.

Link them once, from a clone of this repository, and all three work in every repository:

```sh
ln -s "$(pwd)"/skills/* ~/.claude/skills/
```

## What broke, and what styre does about it

[`docs/lessons.md`](docs/lessons.md) lists the failures from real runs that shaped styre,
with what it does about each. [`docs/architecture.md`](docs/architecture.md) shows how the
parts fit, with diagrams.

[`evals/`](https://github.com/woutersm/styre/tree/main/evals) tests styre's interfaces against
a real model and against run history. The first eval checks whether the builder keeps the
contract its tools and instructions describe. The second scores `styre check`'s warnings
against the phases that went badly in one real project.

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
