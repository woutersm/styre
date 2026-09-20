# styre

An overnight phase orchestrator for the [pi coding agent](https://www.npmjs.com/package/@earendil-works/pi-coding-agent).

Point it at a design document split into phases. It runs one fresh pi process per phase,
serially, unattended. In the morning there is one git commit per phase and logs showing
what happened.

The agent says it is done; styre decides whether it is, by running the gate commands itself
and inspecting the staged diff. Nothing is committed on a red gate.

## Install

```
uv tool install -e .     # editable: the command follows this source tree
uv tool install .        # a copy, pinned to the source as it is right now
```

Use `-e` while styre itself is changing, which is the whole time so far.

⚠️ **`--force` does not rebuild.** A plain `uv tool install` copies a *built wheel* into the
tool's environment, and uv caches that wheel per source path and version. `--force` forces
reinstalling the tool, not rebuilding it, so with the version unchanged it will happily
reinstall a wheel built days ago — and `styre --version` and `styre check` both look perfectly
healthy on a stale build. If you install non-editable, either bump the version or pass
`--no-cache`, and verify by behaviour rather than by the command existing:

```
styre check <design> | tail -1      # exists, proves nothing about which build
wc -c .styre/phase1.prompt.md       # a whole-design prompt means a pre-scoping build
```

`uv tool uninstall styre` removes it. `pip install -e .` works too.

Stdlib only at runtime; pytest is the only dev dependency. Without installing, use
`python -m styre` with the repository on `PYTHONPATH`.

## Use

styre must be run **from inside the target repository** — the project the design describes —
because it switches branches and commits there.

```
styre check design.md                  # print phases, criteria and gates; validate; exit
styre run design.md                    # run every phase
styre run design.md --from-phase 2     # resume after a stop
```

`styre run --help` lists the rest: `--quiet`, `--retries`, `--timeout`, `--gate-timeout`,
`--allow-test-changes`, `--branch`, `--allow-dirty`, `--reset-branch`.

## Design file format

Any preamble, then one block per phase:

````markdown
## Phase 1: Title
What to build.

### Exit criteria
- a statement the agent must make true

### Gate
```
uv sync --locked
uv run pytest -q
```
````

Exit criteria are plain prose for the agent. The **gate** is what the orchestrator enforces.
A phase with no criteria list or no gate block is a hard error.

A phase's prompt does not carry the whole document. It carries the **preamble**, an index of
the phase titles with this one marked, and **that phase's section in full** — the earlier
phases reach it through the decisions log and the previous phase's notes instead. Two things
follow when writing a design:

- Everything in the preamble is sent to every phase, so keep it to what every phase needs.
- Material meant for a human after the last phase belongs in its own file, not in the
  preamble and not after the last `## Phase` heading (anything there is folded into that
  phase).

`example-design.md` is a two-phase example (a `wordfreq` CLI) for testing.

## Layout

| Module | What it is |
| --- | --- |
| `styre/cli.py` | Argument parsing and the `check` / `run` subcommands |
| `styre/config.py` | Constants and `RunOptions` |
| `styre/design.py` | Parsing a design into `Phase` objects, validating it, and building each phase's prompt excerpt |
| `styre/prompts.py` | The builder and fix-round prompts |
| `styre/agents.py` | The `AGENTS.md` block written into the target repo |
| `styre/process.py` | Running children, and rendering pi's JSON event stream |
| `styre/gitops.py` | Git operations |
| `styre/guard.py` | The gate, and the test-tampering guard |
| `styre/state.py` | Reading and judging `phaseN.state.json` |
| `styre/runner.py` | Preflight and the phase loop |
| `orchestrate.py` | Deprecated shim onto `styre.cli` |

## Tests

```
uv run --with pytest python -m pytest -q
```

`tests/fake_pi.py` is a test double installed on `PATH` as `pi`, so the whole loop runs
without a model. `tests/fixtures/*.jsonl` is real captured pi output; parsers are written
against it, not against assumptions.

## Safety

pi has no sandbox and runs commands without asking. Run overnight jobs in an ordinary clone
of the target repo, with only the credentials the job needs, and set a spending limit with
the model provider. styre limits time per run but does not track spend.
