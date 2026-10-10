# What broke, and what styre does about it

Each mechanism in styre was added after a real run failed without it. These are the
failures, with the measurements that came with them. Most came from one personal project
built over 44 phases with a local 27B model. The code comments next to each mechanism repeat
the numbers, so the reason stays with the code.

## Context

On a local model host every token in the context costs prefill time, and it stays for the
rest of the step.

| What happened | What styre does now |
| --- | --- |
| My interactive pi setup, with web tools and a personal `AGENTS.md`, was 47% of every request. | pi runs under styre's own config directory, and `run` refuses to start without one. Fixed overhead per request went from 8,331 to 1,639 tokens. pi 1.0 also loads global skills and MCP servers by itself, so styre passes `--no-skills --no-mcp`. |
| Tool results were 67% of a 60k-token phase, and single reads returned 18,000 characters. | `cap-output.js` limits a `read` to 300 lines and a `bash` call to its first 60 and last 90, with a note on how to get the rest. |
| Reading files was 62% of all command output, and a third of that was a file read a second time. | The `AGENTS.md` block tells the agent to find lines with `grep -n` and read around them with `offset` and `limit`. `evals/interface.py` checks that it does. |
| Reading `docs/decisions.md` was the largest single tool result of a run, about 14,000 tokens in one call. | The agent appends to that file and is told never to read it. No prompt includes it. |
| About 7,500 of 60,000 tokens after 19 steps were thinking from earlier turns, sent again with every request. | `strip-thinking.js` drops earlier thinking before the request leaves pi. |
| Compaction prefilled 48k tokens again, which took 8.5 minutes. On a server without a thinking budget it failed 16 times in one phase, the first two attempts taking 26 minutes each. | styre cancels compaction and restarts a full step from its progress file. |
| One line in a design's preamble said to read `docs/agent-design.md` first. A 2.3 KB phase became a 44 KB context and the model returned nothing. | `styre check` warns when a design names a document the agent would read. |

## Restarting a step

| What happened | What styre does now |
| --- | --- |
| A restarted agent had never written its progress file and spent 80 minutes reading the tree again. | Before a restart, the stopped step gets one more turn in its own cached session, to write that file and nothing else. |
| Told to write only its progress file, one handoff turn went on coding for 42 tool calls. | styre ends the handoff as soon as the progress file changes. |
| The restart line was 60% of the window, set from one server's slowdown curve. On the server that replaced it, writing speed stayed flat from 40k to 80k tokens. | The line moved to 75%. Every restart costs a fresh process reading its way back in. |
| A limit of three restarts stopped two phases that were making progress, each on exactly its third restart. | A phase keeps restarting while each restart changes the tree or the progress file, and stops at the first that changes neither. Six restarts is only the backstop. |
| A fix round for two lint errors began by searching the design and reading the fixtures again. It knew what failed but not what the phase was. | A fix round gets the phase prompt and the progress file with the failure. Below 50% of the window it resumes the failed step's cached session instead. |

## Verification

| What happened | What styre does now |
| --- | --- |
| styre stopped at the first failing gate command. `ruff` failed a 3-hour phase while mypy, the tests and the build had not run, so each fix round found one more failure. | styre runs every gate command and hands the fix round all failures at once. A whole gate takes about 40 seconds. A fix round is a fresh process. |
| A design told the agent to skip a test on non-macOS. The agent did, and the test guard rejected the phase. | `styre check` flags a design that asks for a skip marker before the run starts. |
| The agent's decisions log was passed to later phases. Most of each section repeated what the tree showed, and the rest was status the gate had already proved. | The log is written but never sent to an agent. `notes-next.md`, written for the next phase only, is the one channel between phases. |

## Running unattended

| What happened | What styre does now |
| --- | --- |
| The model host rejected a request for memory and returned an empty stream. styre reported "no state file written", and I spent two days reading the agent's contract for the cause. | An all-zero usage block stops the phase with "the model returned an empty response", which points at the host's log. |
| With `PI_CODING_AGENT_DIR` set in a shell profile, a run started by cron or launchd used a stale config. | styre sets the variable itself for every pi process. |
| A run started without a terminal waited out the whole idle timeout before pi did anything. `pi -p` reads a piped stdin to its end before it starts. | styre closes stdin for pi and for gate commands. The first eval trial found this. |
| A hanging `python` probe inside a phase held a run for 2 hours. | Still open in `TODO.md`. The idle timeout caught it, but only after 2 hours. |
| A resume reused the latest run directory whatever design it had run, and two designs' phases ended up in one run's logs and token counts. | A resume continues the latest run only when that run used the same design file. Otherwise it starts a new run directory and says so. |

## The design

| What happened | What styre does now |
| --- | --- |
| A phase named a new library without an example. Every step spent about 12 `python -c` calls learning its API, and 80% of the phase's output was thinking. | `styre check` flags a new dependency that has no code example. [`skills/styre/writing-designs.md`](../skills/styre/writing-designs.md) says what a phase must give the agent. |
| Six of seven phases gated in two toolchains, a backend and its UI, peaked at 74k to 116k tokens, past the restart line. | `styre check` names those phases once. The heuristic it replaced flagged 12 phases, of which 6 ran large. |
| A warning for large phases, by prompt size or number of criteria, flagged 5 phases. None of them went badly. | The warning was deleted. [`evals/advisories.py`](../evals/advisories.py) scores every warning against the run history. |

## Evaluating it

- The first full eval run scored 29 of 30. The one failure was in the check: it read
  `cat > docs/decisions.md <<'EOF'` as reading `tax.py`, because the heredoc mentioned the
  file. Before a failure counts against the model, look at the check.
- Every interface scenario now passes 5 of 5 on the model I use. That catches regressions
  in styre's prompts and tools, but it cannot tell two models apart.
- The warnings were written from the same runs they are scored on. A good score shows a
  warning describes its own history. A bad score even in-sample is the signal worth acting on.

## What was built and removed

styre once had an automatic Claude review of each run, Claude as an escape hatch for a stuck
phase, a check of the design against the repository, a web viewer and hidden held-out tests.
All of them were removed. The first four put judgement into a tool whose job is to run, gate
and commit. The held-out tests were more complexity than they were worth. Judgement now
belongs to the director, as [`skills/styre/DIRECTOR.md`](../skills/styre/DIRECTOR.md) sets out.
