# Architecture

styre is a loop around pi. It reads a design, starts one pi process per step of a phase, runs
the gate itself, and commits. It calls no model and makes no network request of its own.
Everything it knows about a run is in files and git.

## The parts

```mermaid
flowchart LR
    director["Director<br/>a person, or a person<br/>with Claude Code"]
    design[("design.md")]
    subgraph styre["styre (Python, stdlib only)"]
        cli["cli.py<br/>design · check · run · summarize"]
        runner["runner.py<br/>the phase loop"]
        guard["guard.py<br/>gate + test guard"]
        summarize["summarize.py<br/>the report"]
    end
    subgraph pi["pi process, one per step"]
        agent["builder agent"]
        ext["styre extensions<br/>cap-output · no-compaction<br/>strip-thinking · styre-tools"]
    end
    host["model host<br/>local or hosted"]
    repo[("target repo<br/>git + .styre/")]

    director -- writes --> design
    director -- "styre run / summarize" --> cli
    design --> cli --> runner
    runner -- "prompt file, flags" --> pi
    agent <--> ext
    pi <-- requests --> host
    agent -- "edits code,<br/>writes .styre/ files" --> repo
    runner -- "reads .styre/, stages, commits" --> repo
    runner --> guard -- "runs gate commands" --> repo
    runner -- timeline.jsonl --> summarize
    summarize -- summary.md --> director
```

The director and the model host are outside styre. The director makes every decision that
needs judgement: what the design says, what a stop means, whether the result is good. The
model host is wherever pi's config points.

## Modules

Each module has one job.

| Module | Job |
| --- | --- |
| `cli.py` | The `design`, `check`, `run` and `summarize` subcommands; `design` only opens interactive `claude` on `/styre-design` |
| `config.py` | Constants, the pi invocation, the context fractions, `RunOptions` |
| `design.py` | Parses a design into phases, validates it, and produces `check`'s warnings |
| `prompts.py` | Writes the phase prompt, the fix-round prompts, the handoff and the relay prompt |
| `agents.py` | The block styre writes into the target repository's `AGENTS.md` |
| `runner.py` | Preflight and the phase loop |
| `process.py` | Runs gate commands and git, streams pi's events, and kills a silent pi |
| `guard.py` | Runs the gate and checks the staged diff for test tampering |
| `gitops.py` | Every git call |
| `rundir.py` | Paths inside `.styre/runs/<id>/` |
| `state.py` | Reads and judges the agent's state file |
| `timeline.py` | Appends measured events to `timeline.jsonl` and flushes each line |
| `summarize.py` | Reads a run back from disk and writes `summary.md` |
| `pi_extensions/*.js` | Loaded into every pi process with `--extension` |

## One phase

```mermaid
flowchart TD
    start([phase N]) --> prompt["write the prompt:<br/>preamble, phase index, this phase,<br/>the previous phase's notes"]
    prompt --> step["start a fresh pi process"]
    step --> ended{"how did<br/>the step end?"}
    ended -- "context past 75%" --> relays{"did the last fresh<br/>start change the tree<br/>or the progress file?"}
    relays -- yes --> handoff["one resumed turn:<br/>write the progress file"]
    handoff --> step
    relays -- no --> stop
    ended -- "pi exited non-zero,<br/>or went silent" --> stop
    ended -- "agent called styre_finish" --> state{"state file:<br/>DONE?"}
    state -- "BLOCKED, missing,<br/>or empty response" --> stop
    state -- DONE --> gate["styre runs every gate command,<br/>then the test guard"]
    gate -- green --> diff{"anything staged?"}
    diff -- yes --> commit(["commit, titled after the phase"])
    diff -- no --> stop
    gate -- red --> retries{"fix rounds left?"}
    retries -- yes --> fix["fix round: the whole failure,<br/>resumed if the step ended<br/>below 50%, otherwise fresh"]
    fix --> step
    retries -- no --> stop(["stop: work left uncommitted"])
```

A run is these phases in order. The first phase that stops ends the run, and
`--from-phase N` resumes it in the same run directory when the latest run used the same
design file.

## One step, in detail

```mermaid
sequenceDiagram
    participant S as styre
    participant P as pi + extensions
    participant M as model host
    participant R as target repo

    S->>R: write .styre/phase.json (gate, timeout)
    S->>P: pi -p --mode json --no-skills --no-mcp<br/>--extension ... @phaseN.prompt.md
    loop each turn
        P->>M: request (earlier thinking stripped)
        M-->>P: response with tool calls
        P->>R: read, edit, bash (results capped)
        opt agent checks its work
            P->>R: styre_gate runs the gate commands
            R-->>P: pass or fail per command
        end
        P->>R: styre_progress writes .styre/progress.md
        P-->>S: JSON events on stdout
        Note over S: tracks context size,<br/>idle timer, empty responses
    end
    P->>R: styre_finish writes phaseN.state.json<br/>(refuses DONE after a red gate)
    P-->>S: exit 0
    S->>R: move state, notes and progress into .styre/runs/<id>/
    S->>R: run the gate again, check the staged diff
    S->>R: git commit
```

The agent's own gate run and styre's are the same commands with the same timeout. Only
styre's run decides whether the phase is committed. `styre_finish` refusing DONE after a red
gate saves a step. It does not replace the check.

## Context management

On a local model host every token in the context costs prefill time and stays for the rest of
the step. styre follows three rules:

1. Keep tokens out at the source. `cap-output.js` limits a `read` to 300 lines and a `bash`
   result to its first 60 and last 90 lines. `strip-thinking.js` drops earlier thinking from
   each request.
2. Never rewrite the conversation, because that invalidates the prompt cache.
   `no-compaction.js` cancels pi's compaction.
3. When a step fills up, restart it from a file, not from a summary.

```mermaid
sequenceDiagram
    participant S as styre
    participant A as step k
    participant B as step k+1

    A->>S: turn ends, context 91k of 120k
    Note over S: past 75%: stop at the turn end
    S->>A: resume the same session for one turn:<br/>"write your progress file, nothing else"
    A->>S: .styre/progress.md (Done / Now / Next / Learned)
    S->>B: fresh process: the phase prompt<br/>+ a relay prompt with the progress file
    Note over S,B: if step k+1 changes neither the tree<br/>nor the progress file, the phase stops
```

The fractions come from `contextWindow` in styre's pi config. A fix round below 50% of the
window resumes the failed step's session, which the model host still has cached. Above 50%,
the fix round starts a fresh process.

## What lives where

```
target repo/
  AGENTS.md                 styre's rules block, committed. pi loads it into every request.
  docs/decisions.md         the agent's log, append-only, committed, never read back to an agent
  .styre/                   excluded from git
    latest.txt              the most recent run
    phase.json              what styre_gate needs: the phase number, gate and timeout
    progress.md             the agent's working notes for the current phase
    notes-next.md           the agent's note to the next phase
    phaseN.state.json       written by styre_finish: DONE or BLOCKED, and why
    runs/<YYYYmmdd-HHMMSS>/
      phaseN.prompt.md, phaseN.fixR.md, phaseN.handoffK.md, phaseN.relayK.md
      phaseN.state.json, phaseN.notes-next.md, phaseN.progress.md
      logs/phaseN.log, logs/phaseN.events.jsonl
      sessions/phaseN/      pi's own sessions, used to resume a step
      timeline.jsonl        what styre did and when, measured by styre
      summary.md            the report
```

Each kind of handoff lasts as long as it needs to:

| File | Written by | Read by | Lasts |
| --- | --- | --- | --- |
| `progress.md` | the agent, through `styre_progress` | fresh starts and fix rounds of the same phase | one phase |
| `notes-next.md` | the agent | the next phase's prompt | one phase boundary |
| `docs/decisions.md` | the agent | people, in git | permanently, never sent to an agent |
| `phaseN.state.json` | `styre_finish` | styre, before it runs the gate | one step |
| `timeline.jsonl` | styre | `summarize` | permanently, per run |

## Why the agent's account is not trusted

The state file and the decisions log are the agent's own report. styre uses the state file
only to learn whether the agent says DONE or BLOCKED. Everything else that decides a phase
comes from styre's own measurements:

- styre runs the gate commands itself after the agent exits
- the test guard compares the staged diff for added skip or xfail markers and a net loss of
  test functions
- the timeline records durations, return codes, context sizes and commit hashes that styre
  measured
- `summary.md` is computed from the timeline

## pi runs isolated

Every pi process gets `PI_CODING_AGENT_DIR=~/.config/pi/styre`, so it does not load the
person's interactive extensions or `AGENTS.md`. `--no-skills` and `--no-mcp` turn off what pi
1.0 discovers on its own. stdin is closed, because `pi -p` reads a piped stdin to its end
before it starts. A pi process that prints nothing for `--timeout` seconds is killed with its
whole process group, so its children release ports and locks before the next step.
