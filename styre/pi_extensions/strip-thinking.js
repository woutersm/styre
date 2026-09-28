// Drop earlier thinking from every model request.
//
// pi sends each earlier assistant message's thinking back in the field it arrived in
// (`reasoning_content` from modelhost), and modelhost's chat template renders all of it, so every
// step re-reads every earlier step's thinking. mlxserve dropped it with the template flag
// `preserve_thinking: false`; modelhost ignores chat_template_kwargs, so it is dropped here,
// before the request leaves pi. Measured on app phase 3 (2026-09-28): ~7.5k of 60k tokens
// of context after 19 steps was replayed thinking, and the share grows every step.
const REASONING_FIELDS = ["reasoning_content", "reasoning", "reasoning_text", "reasoning_details"];

export default function stripThinking(pi) {
  pi.on("before_provider_request", (event) => {
    const payload = event.payload;
    if (!payload || !Array.isArray(payload.messages)) return undefined;
    for (const message of payload.messages) {
      if (message && message.role === "assistant") {
        for (const field of REASONING_FIELDS) delete message[field];
      }
    }
    return payload;
  });
}
