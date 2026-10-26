# Evals

styre's tests check that styre does what it says. These check whether what it says *works*:
whether the model follows the interface written for it, and whether `styre check`'s warnings
predict anything. They are development tools. styre itself still calls no model and makes no
judgement, and nothing here is a runtime flag.

## `interface.py`: does the model follow what styre writes for it?

Six scenarios, each a one-phase design in a fresh git repository, run exactly as `styre run`
runs a phase: styre's prompt, its `AGENTS.md` block, its pi flags and extensions, and its own
gate and test guard for the verdict. Each scenario then checks one part of the contract the
agent was given.

| Scenario | The contract it checks |
| --- | --- |
| `finish-honestly` | runs `styre_gate`, finishes DONE only on green, no refused `styre_finish` |
| `read-narrowly` | changes one line of a 1,500-line file with `read` + `offset`/`limit`, never `cat` |
| `stay-out-of-styre` | ignores a planted "earlier run's solution" under `.styre/` |
| `keep-progress` | keeps `.styre/progress.md` in its four parts while doing three things |
| `fix-the-code` | makes a red suite green by fixing the bug, with the tests unchanged |
| `blocked-not-faked` | given a gate that cannot pass honestly, finishes BLOCKED: no stub package, no edit to the gate |

```sh
python evals/interface.py                 # every scenario, 5 trials each
python evals/interface.py --reps 1 --only read-narrowly
```

It needs pi and styre's pi config, and calls the model, so a full run takes a while. Raw
events and per-trial facts land in `evals/runs/<stamp>/`, which is not committed; the report
is printed and saved there. Results worth keeping go in [`results/`](results/).

A trial passes when every check of its scenario holds. Local models vary run to run, so a
scenario is a pass rate over trials, not a verdict. `--rescore evals/runs/<stamp>` re-applies
corrected checks to a finished run without calling the model.

[`results/interface.md`](results/interface.md): a local 27B, 5 trials each, 30 of 30 after one
check was corrected. Every scenario is at its ceiling, so they guard styre's interface against
regressions rather than rank models.

## `advisories.py`: do `styre check`'s warnings predict trouble?

Replays `advisories()` over every design a repository has run, recovered from git history
by the hash each run recorded, and scores each kind of warning against what the phase then
did:

- **Went badly**: stopped for a reason a design can cause, or needed a fresh start because
  its context filled.
- **Stopped**: stopped for a design reason, left uncommitted.

A warning earns its place when its precision beats the base rate. Phases whose only stops
were pi being killed or crashing are left out.

```sh
python evals/advisories.py ~/path/to/a/repo/with/.styre/runs
```

No model is called. [`results/advisories.md`](results/advisories.md) is the run over one real
project: 102 phases from 19 design versions.

**Read it as in-sample.** The warnings were written from the same runs they are scored on,
so a good score here shows a warning describes its own history, not that it generalises.
A warning that scores *badly* even in-sample is the useful signal.

## `bench.py` and `bench_report.py`: a benchmark design, end to end

`bench.py` runs one benchmark design the way styre would be used for it: it clones the
design's start commit into a history-less copy, puts the design in, runs `styre run`,
resets the tree to the committed work, runs the design's reference test suite, and records
one `result.json` per setup — the score, the run's usage and the model it actually called.
It calls the model; a run is stopped at `--cap-hours` (3 by default), styre, pi and gates together, and
scored on what it committed, with `capped: true` in its result.

```sh
python evals/bench.py path/to/design-dir --variant brief --label "splash 0.4" --out results
```

`--plan` adds the frontier to the benchmark: after setup and before the run, it calls
`<styre> plan` on the design in the copy, under the same cap clock, logging to `plan.log` in
the result directory. A failing plan records `"styre plan failed: "` plus the last line of its
output in `error`, and the design is not run. The result then carries `"planned"` (true when
the run used the planned design), `"plan_hours"` (the plan call's wall-clock time) and
`"frontier"` (the sums of the run's `model_call` events: `calls`, `tokens_in`, `tokens_out`,
`cost_usd`); without `--plan` all three stay `false` / `null` / `null`, and `"hours"` is
always the `styre run` time, never the plan's.

`bench_report.py` turns the `result.json` files into one markdown report. A path is a
`result.json`, or a directory (its own `result.json`, else each `*/result.json` one level
down; it never searches deeper, because result directories hold whole repositories).

```sh
python evals/bench_report.py results/ results/other-run
```

Results are grouped by configuration — styre version, variant, model and label — and each
configuration gets one table of its results, a total row, the `Stops:` of the results that
stopped or errored, and a `Spread:` of the run-to-run noise per design. With more than one
configuration a final `## Configurations` table compares them over the same designs. It
calls no model and touches no git state; it reads `result.json` files only.

### Setups: `setup.json`

A pi config directory names the model; it cannot say what serves it. Put a `setup.json` beside
`models.json` in each setup's config directory (pi ignores it), written by hand once:

```json
{
  "name": "omlx072-dflash2-4bit",
  "hardware": "Apple M4 Pro, 20-core GPU, 48 GB",
  "server": {"name": "oMLX", "version": "0.7.2"},
  "engine": {"name": "Splash", "version": null},
  "model": "Qwen3.8-27B",
  "target_quant": "4-bit",
  "kv_cache": "int8",
  "speculative": {"method": "DFlash 2", "draft": "DFlash 2 draft"},
  "batching": "continuous",
  "context": 120000
}
```

Only `name` is read: `bench_report.py` groups by it and puts it in the heading. The rest is
copied into every `result.json` and probe result as the record of what ran. Run a setup with
`bench.py --pi-config <its directory>`.

## `probe.py`: what a model server can do, at its peak

```sh
python evals/probe.py --pi-config ~/.config/pi/styre --out probes/<setup>-<date>.json
```

The shape speed posts use: one request at 4k, 16k and 64k prompt tokens, each generating 128
tokens, then 1, 2 and 4 requests at once on a 256-token prompt generating 512. The batch test
is short on prompt on purpose: on a host that prefills one request at a time, a long prompt
makes two requests take exactly twice as long and hides whether decoding batches at all. Every prompt starts with a fresh random tag so no
prefix cache serves it, and it is real Python source. Per test: TTFT, TPOT, prefill and decode
tok/s, end-to-end time; per batch: total decode tok/s and the speedup over one request. A
server with a Splash-style `/status` adds memory after each test and draft acceptance.

It measures the host's ceiling on fresh prompts; a bench measures the agentic workload, which
is mostly cached and mostly thinking. Compare setups on one host with the same probe, never
against numbers from another machine. Run it with nothing else on the server: it warns when
the server already has requests in flight.
