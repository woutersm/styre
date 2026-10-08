# styre

Run a phased design through the [pi coding agent](https://www.npmjs.com/package/@earendil-works/pi-coding-agent)
overnight, unattended, and wake up to one git commit per phase.

You write a design document split into phases. Each phase says what to build, what must be
true when it is done, and which commands prove it: the **gate**. styre gives each phase to a
fresh pi process, then runs the gate itself and checks the staged diff. The agent saying it is
done counts for nothing; a phase is committed only when the gate is green and no test was
skipped or deleted. When a gate fails, the agent gets the failure back and another try, a
limited number of times.

It was built for one person's nights with a local 27B model, and it shows: everything in it
exists because a run failed without it. The reasoning, with measurements, is in
[`CLAUDE.md`](https://github.com/woutersm/styre/blob/main/CLAUDE.md).

> **Status: alpha.** Tested on macOS with pi 0.87 and local models served over an
> OpenAI-compatible API. Expect rough edges anywhere else.

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

```sh
mkdir -p ~/.config/pi/styre
cp ~/.config/pi/agent/models.json ~/.config/pi/agent/auth.json ~/.config/pi/styre/
echo '{}' > ~/.config/pi/styre/settings.json
```

Keep it lean: no `packages`, and no `AGENTS.md` beside it. Pin the model in its
`settings.json` (`defaultProvider`, `defaultModel`), and set the model's `contextWindow` in
`models.json`: styre restarts a phase in a fresh process at 75% of it.

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
a stopped phase needs, and reviewing the result are for whoever directs the run — a person,
or a person with an interactive assistant. [`skill/DIRECTOR.md`](https://github.com/woutersm/styre/blob/main/skill/DIRECTOR.md)
is the five rules that work for us; [`skill/writing-designs.md`](https://github.com/woutersm/styre/blob/main/skill/writing-designs.md)
is how to shape a design so a local model can finish it.

Both live in [`skill/`](https://github.com/woutersm/styre/tree/main/skill), which is also a
[Claude Code](https://claude.com/claude-code) skill: link it in once and `/styre` works in every
repository.

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
