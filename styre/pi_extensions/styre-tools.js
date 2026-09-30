// Three tools that replace files and conventions the agent used to handle by hand.
//
// - styre_gate runs the phase's gate — the same commands, the same shell, the same timeout the
//   orchestrator's `guard.verify` uses — and returns what failed as data, not as a log the
//   agent has to read back. Every run is recorded in .styre/phaseN.gates.jsonl.
// - styre_progress writes .styre/progress.md in its four-part shape.
// - styre_finish writes .styre/phaseN.state.json. It refuses DONE unless the last styre_gate
//   run passed, and counts fix_rounds_self from the recorded runs rather than asking for it.
//
// The files are the ones the orchestrator already reads, so nothing downstream changes. The
// orchestrator writes .styre/phase.json (phase number, gate, gate timeout) before each phase.
// Parameters are plain JSON Schema: pi validates those without TypeBox, so this file imports
// only Node and runs on its own in tests.

import { spawn } from "node:child_process";
import { appendFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const TAIL_LINES = 60;
const TAIL_CHARS = 4000;
const PROGRESS_MAX_LINES = 40;

const tail = (text) => {
  const lines = (text.endsWith("\n") ? text.slice(0, -1) : text).split("\n");
  return lines.slice(-TAIL_LINES).join("\n").slice(-TAIL_CHARS);
};

const WINDOWS = process.platform === "win32";

// One command as `process.run(cmd, shell=True)` runs it: the platform's shell (/bin/sh, or
// cmd.exe on Windows), stdout and stderr merged, its own process group on POSIX so a timeout
// takes the whole tree, exit 124 on a timeout.
function runOne(command, cwd, timeoutS) {
  return new Promise((resolve) => {
    const started = Date.now();
    const child = spawn(command, { cwd, shell: true, detached: !WINDOWS });
    let out = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (out += d));
    let timedOut = false;
    const timer = timeoutS
      ? setTimeout(() => {
          timedOut = true;
          try {
            if (WINDOWS) child.kill();
            else process.kill(-child.pid, "SIGKILL");
          } catch { /* already gone */ }
        }, timeoutS * 1000)
      : null;
    child.on("close", (code) => {
      if (timer) clearTimeout(timer);
      const exit = timedOut ? 124 : code ?? 1;
      if (timedOut) out += "\n[styre] TIMEOUT";
      resolve({ command, exit, seconds: Math.round((Date.now() - started) / 100) / 10, out });
    });
  });
}

// Every command runs, even after one fails, as the orchestrator's gate does.
export async function runGate(commands, cwd, timeoutS) {
  const results = [];
  for (const command of commands) results.push(await runOne(command, cwd, timeoutS));
  return {
    passed: results.every((r) => r.exit === 0),
    commands: results.map(({ command, exit, seconds }) => ({ command, exit, seconds })),
    failures: results.filter((r) => r.exit !== 0)
      .map(({ command, exit, out }) => ({ command, exit, tail: tail(out) })),
  };
}

export function formatProgress({ done, now, next, learned }) {
  const text = `Done: ${done}\nNow: ${now}\nNext: ${next}\nLearned: ${learned}\n`;
  const count = text.split("\n").length - 1;
  if (count > PROGRESS_MAX_LINES) {
    throw new Error(`The progress file is ${count} lines; keep it to ${PROGRESS_MAX_LINES} lines.`);
  }
  return text;
}

export function finishState({ status, reason, unmet_criteria = [] }, phase, gateRuns) {
  if (status === "DONE") {
    if (gateRuns.length === 0) throw new Error("Run styre_gate before finishing: DONE needs a green gate.");
    if (!gateRuns[gateRuns.length - 1].passed) {
      throw new Error("The last styre_gate run failed. Fix it and run styre_gate again, or finish BLOCKED.");
    }
    if (unmet_criteria.length > 0) {
      throw new Error("DONE with unmet criteria is rejected: finish BLOCKED and list them.");
    }
  } else if (!reason) {
    throw new Error("BLOCKED needs a one-line reason.");
  }
  const state = { phase, status };
  if (status === "BLOCKED") state.reason = reason;
  state.unmet_criteria = unmet_criteria;
  state.fix_rounds_self = gateRuns.filter((r) => !r.passed).length;
  return state;
}

function phaseInfo(cwd) {
  const path = join(cwd, ".styre", "phase.json");
  if (!existsSync(path)) throw new Error("No .styre/phase.json: these tools only work inside a styre run.");
  return JSON.parse(readFileSync(path, "utf-8"));
}

const gateLog = (cwd, phase) => join(cwd, ".styre", `phase${phase}.gates.jsonl`);

function gateRuns(cwd, phase) {
  const path = gateLog(cwd, phase);
  if (!existsSync(path)) return [];
  return readFileSync(path, "utf-8").split("\n").filter(Boolean).map((line) => JSON.parse(line));
}

const text = (value) => ({
  content: [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value, null, 1) }],
  details: undefined,
});

export default function (pi) {
  pi.registerTool({
    name: "styre_gate",
    label: "styre gate",
    description:
      "Run this phase's gate: exactly the commands the orchestrator runs afterwards. Returns " +
      "whether it passed, each command's exit code, and the last lines of each failure.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
    async execute(_id, _params, _signal, _onUpdate, ctx) {
      const info = phaseInfo(ctx.cwd);
      const result = await runGate(info.gate, ctx.cwd, info.gate_timeout);
      appendFileSync(gateLog(ctx.cwd, info.phase),
        JSON.stringify({ passed: result.passed, at: new Date().toISOString() }) + "\n");
      return text(result);
    },
  });

  pi.registerTool({
    name: "styre_progress",
    label: "styre progress",
    description:
      "Overwrite your progress file (.styre/progress.md). Call it after every step that " +
      "finishes something. A restarted process gets only this and the working tree. At most 40 lines.",
    parameters: {
      type: "object",
      properties: {
        done: { type: "string", description: "What is finished and verified: files, tests, gate commands that pass" },
        now: { type: "string", description: "What you are in the middle of" },
        next: { type: "string", description: "What is left, in order" },
        learned: { type: "string", description: "Facts the tree does not show: a command that works, a trap, a decision" },
      },
      required: ["done", "now", "next", "learned"],
      additionalProperties: false,
    },
    async execute(_id, params, _signal, _onUpdate, ctx) {
      writeFileSync(join(ctx.cwd, ".styre", "progress.md"), formatProgress(params));
      return text("Progress written.");
    },
  });

  pi.registerTool({
    name: "styre_finish",
    label: "styre finish",
    description:
      "Record the phase's result. DONE needs the last styre_gate run to have passed and no " +
      "unmet criteria; otherwise BLOCKED with a reason and the exact text of each unmet criterion.",
    parameters: {
      type: "object",
      properties: {
        status: { type: "string", enum: ["DONE", "BLOCKED"] },
        reason: { type: "string", description: "One line; required when BLOCKED" },
        unmet_criteria: { type: "array", items: { type: "string" },
                          description: "The exact text of each exit criterion not fully met" },
      },
      required: ["status"],
      additionalProperties: false,
    },
    async execute(_id, params, _signal, _onUpdate, ctx) {
      const info = phaseInfo(ctx.cwd);
      const state = finishState(params, info.phase, gateRuns(ctx.cwd, info.phase));
      writeFileSync(join(ctx.cwd, ".styre", `phase${info.phase}.state.json`), JSON.stringify(state, null, 2) + "\n");
      return text(state);
    },
  });
}
