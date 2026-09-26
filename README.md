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
styre check <design> | tail -1                 # exists, proves nothing about which build
wc -c .styre/runs/*/phase1.prompt.md           # an oversized prompt means a stale build
```

`uv tool uninstall styre` removes it. `pip install -e .` works too.

Stdlib only at runtime; pytest is the only dev dependency. Without installing, use
`python -m styre` with the repository on `PYTHONPATH`.

## A pi config of its own (required)

styre runs pi with `PI_CODING_AGENT_DIR=~/.config/pi/styre`, and preflight refuses to start
without it. An unattended run should not inherit an interactive setup: on one real machine
the operator's config put 11.5 KB of web-search tool schemas and a 10.9 KB writing-style
`AGENTS.md` into **every request of every turn** — 47% of a phase's context, for an agent
with no network tests and no human reading its prose. Removing them cut the fixed overhead
of a trivial prompt from 8,331 tokens to 1,639.

```
mkdir -p ~/.config/pi/styre
cp ~/.config/pi/agent/models.json ~/.config/pi/agent/auth.json ~/.config/pi/styre/
echo '{}' > ~/.config/pi/styre/settings.json
```

Keep it lean: **no `packages`, and no `AGENTS.md` beside it.** The target repo's own
`AGENTS.md` still reaches the agent — pi finds it in the working directory.

If your model is served from a memory-constrained host, set a thinking budget there too;
an unbounded reasoning block is the fastest way to exhaust a KV cache. See CLAUDE.md,
"Where the model runs".

## Use

styre must be run **from inside the target repository** — the project the design describes —
because it switches branches and commits there.

```
styre check design.md                  # validate, print phases and gates, and find repo
                                       #   code each phase's prose already names
styre run design.md                    # run every phase
styre run design.md --from-phase 2     # resume after a stop, in the latest run directory
styre summarize                        # what happened in the last run
```

`styre run --help` lists the rest: `--quiet`, `--retries`, `--timeout` (seconds of *silence*
from pi, not total runtime), `--gate-timeout`, `--allow-test-changes`, `--branch`,
`--allow-dirty`, `--reset-branch`, `--run-id`, and `--claude-touch` — which gives Claude one
bounded turn at a phase that stopped, off by default because it is real spend.

While a phase runs, `<run>/logs/phaseN.log` is written live, so `tail -f` follows it.

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
the phase titles with this one marked, and **that phase's section in full**. Earlier phases
reach it only through the previous phase's `notes-next.md` and through the working tree
itself. Three things follow when writing a design:

- Everything in the preamble is sent to every phase, so keep it to what every phase needs.
- **Never tell a phase to read a reference document.** One preamble line — *"the design
  means `docs/agent-design.md`, read it first"* — turned a 2.3 KB phase into a 44 KB
  context, and the local model returned an empty response. If a reference document is
  organised per module, fold each section into its phase and stop shipping the document.
- Material meant for a human after the last phase belongs in its own file, not in the
  preamble and not after the last `## Phase` heading (anything there is folded into that
  phase).

Keep phases small. A phase whose title contains "and" is usually two phases: one that was
split in half went from failing three times to committing on the first try.

`example-design.md` is a two-phase example (a `wordfreq` CLI) for testing.

## Layout

| Module | What it is |
| --- | --- |
| `styre/cli.py` | Argument parsing and the `check` / `run` / `summarize` subcommands |
| `styre/config.py` | Constants, `PI_CONFIG_DIR`, and `RunOptions` |
| `styre/design.py` | Parsing a design into `Phase` objects, validating it, and building each phase's prompt excerpt |
| `styre/prompts.py` | The builder and fix-round prompts |
| `styre/agents.py` | The `AGENTS.md` block written into the target repo |
| `styre/review.py` | Cross-referencing a phase's prose against existing test files |
| `styre/process.py` | Running children, and rendering pi's JSON event stream |
| `styre/gitops.py` | Git operations |
| `styre/guard.py` | The gate, and the test-tampering guard |
| `styre/state.py` | Reading and judging `phaseN.state.json` |
| `styre/rundir.py` | The per-run directory under `.styre/runs/` |
| `styre/timeline.py` | `timeline.jsonl`, the orchestrator's own record of a run |
| `styre/summarize.py` | Reading a finished run back off disk. Calls no model |
| `styre/touch.py` | Claude's one bounded turn at a stuck phase (`--claude-touch`) |
| `styre/runner.py` | Preflight and the phase loop |
| `orchestrate.py` | Deprecated shim onto `styre.cli` |

## Tests

```
uv run --with pytest python -m pytest -q
```

`tests/fake_pi.py` and `tests/fake_claude.py` are test doubles installed on `PATH` as `pi`
and `claude`, so the whole loop — `--claude-touch` included — runs without a model. `tests/fixtures/*.jsonl` is real captured pi output; parsers are written
against it, not against assumptions.

## Safety

pi has no sandbox and runs commands without asking. Run overnight jobs in an ordinary clone
of the target repo, with only the credentials the job needs, and set a spending limit with
the model provider. styre limits time per run but does not track spend.
