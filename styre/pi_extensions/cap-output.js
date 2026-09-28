// Cap what a `read` or a `bash` call puts into the model's context, at the moment it does.
//
// Tool results are most of a phase's context: 67% of a 60k app phase at step 19, with single
// reads of 18,000 characters (2026-09-28). pi's own limits are 2,000 lines or 50 KB per call —
// ~14k tokens in one step — and every token that enters costs prefill time on a local model host
// (~9 ms each on an M4 Pro) and stays for the rest of the phase.
//
// The cap is applied through `tool_result`, when the result first enters the conversation, so
// the capped text is what pi stores and resends from then on. The conversation's prefix never
// changes afterwards and the prompt cache stays valid — unlike trimming old results later,
// which would force the whole context to be prefilled again.
//
// A read with an explicit `limit` is the agent reading narrowly already: only the character cap
// applies to it. Everything cut says so, and says how to get the rest.

const READ_MAX_LINES = 300;
const BASH_HEAD_LINES = 60;
const BASH_TAIL_LINES = 90; // a failing test run's reason is at the end
const MAX_CHARS = 16000;

function capChars(text) {
  return text.length <= MAX_CHARS ? text : text.slice(0, MAX_CHARS);
}

// A trailing newline is not a line of output.
const linesOf = (text) => (text.endsWith("\n") ? text.slice(0, -1) : text).split("\n");

export function capRead(text, input) {
  const lines = linesOf(text);
  const offset = Number(input?.offset) || 1;
  const explicitLimit = input?.limit !== undefined && input?.limit !== null;
  if (explicitLimit || lines.length <= READ_MAX_LINES) {
    if (text.length <= MAX_CHARS) return null;
    return (
      capChars(text) +
      `\n[styre: this read was cut at ${MAX_CHARS} characters of ${text.length}. ` +
      "Read a smaller range with offset and limit, or grep for what you need.]"
    );
  }
  const kept = capChars(lines.slice(0, READ_MAX_LINES).join("\n"));
  const shown = kept.split("\n").length;
  return (
    kept +
    `\n[styre: showing lines ${offset}-${offset + shown - 1} of the ${lines.length} this read returned. ` +
    `Continue with offset=${offset + shown} and a limit, or grep for the lines you need.]`
  );
}

export function capBash(text) {
  const lines = linesOf(text);
  if (lines.length <= BASH_HEAD_LINES + BASH_TAIL_LINES && text.length <= MAX_CHARS) return null;
  if (lines.length > BASH_HEAD_LINES + BASH_TAIL_LINES) {
    const head = lines.slice(0, BASH_HEAD_LINES).join("\n");
    const tail = lines.slice(-BASH_TAIL_LINES).join("\n");
    const omitted = lines.length - BASH_HEAD_LINES - BASH_TAIL_LINES;
    return (
      capChars(head) +
      `\n[styre: ${omitted} lines omitted of ${lines.length}. Narrow the command with grep, head or tail.]\n` +
      capChars(tail)
    );
  }
  const half = MAX_CHARS / 2;
  return (
    text.slice(0, half) +
    `\n[styre: ${text.length - MAX_CHARS} characters omitted of ${text.length}. ` +
    "Narrow the command with grep, head or tail.]\n" +
    text.slice(-half)
  );
}

export default function capOutput(pi) {
  pi.on("tool_result", (event) => {
    const cap = event.toolName === "read" ? (t) => capRead(t, event.input)
      : event.toolName === "bash" ? capBash
      : null;
    if (!cap || !Array.isArray(event.content)) return undefined;
    let changed = false;
    const content = event.content.map((part) => {
      if (part?.type !== "text" || typeof part.text !== "string") return part;
      const capped = cap(part.text);
      if (capped === null) return part;
      changed = true;
      return { ...part, text: capped };
    });
    return changed ? { content } : undefined;
  });
}
