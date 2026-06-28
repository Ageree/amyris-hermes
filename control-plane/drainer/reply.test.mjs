// Self-check for the Eve reply-selection (the cold-start/elicitation hardening).
// Run (env sourced so the module's top-level checks pass):
//   node control-plane/drainer/reply.test.mjs
import assert from "node:assert";
import { foldEvent, selectReply } from "./drainer.mjs";

const run = (events) => selectReply(events.reduce((s, e) => foldEvent(s, e), { stop: "", any: "" }));
const mc = (message, finishReason) => ({ type: "message.completed", data: { message, finishReason } });

// 1. Clean single answer.
assert.equal(run([mc("привет", "stop")]), "привет");

// 2. Tool-call ack THEN final stop → the stop answer wins (real two-bubble turn).
assert.equal(run([mc("принято 🙌", "tool-calls"), mc("вот ответ [[remember:x]]", "stop")]), "вот ответ [[remember:x]]");

// 3. Tool-call / elicitation ONLY, no final stop → fall back to the ack (never drop the reply).
assert.equal(run([mc("уточню пару моментов", "tool-calls")]), "уточню пару моментов");

// 4. No text at all (cold-start malformed turn) → "" so callEve retries.
assert.equal(run([{ type: "session.started" }, { type: "turn.completed" }]), "");
assert.equal(run([mc("", "stop")]), "", "empty message body is not a reply");

// 5. Last stop wins if several arrive.
assert.equal(run([mc("первый", "stop"), mc("второй", "stop")]), "второй");

console.log("reply self-check PASS");
