// Self-check for scoped (per-user container) mode: claimSpec picks the right Convex
// claim mutation by whether USER_ID is set. Scoped → messages:claimNextForUser with the
// userId arg (a container drains ONLY its tenant); unset → messages:claimNextAny (the
// shared Mac drainer, UNCHANGED). workerSecret is injected by convex(), not here.
// No env needed (drainer.mjs validates env only when run as the loop).
//   node control-plane/drainer/scoped.test.mjs
import assert from "node:assert";
import { claimSpec } from "./drainer.mjs";

// 1. USER_ID set → scoped claim for exactly that user.
let s = claimSpec({ USER_ID: "kx70d27zabc" });
assert.equal(s.path, "messages:claimNextForUser");
assert.deepEqual(s.args, { userId: "kx70d27zabc" });

// 2. USER_ID unset → shared claim, no userId arg (Mac drainer path unchanged).
s = claimSpec({});
assert.equal(s.path, "messages:claimNextAny");
assert.deepEqual(s.args, {});

// 3. Empty-string USER_ID is treated as unset (a blank env var must not scope).
s = claimSpec({ USER_ID: "" });
assert.equal(s.path, "messages:claimNextAny");
assert.deepEqual(s.args, {});

// 4. Defaults to process.env when called with no arg (the real main() path).
process.env.USER_ID = "kx99scoped";
s = claimSpec();
assert.equal(s.path, "messages:claimNextForUser");
assert.deepEqual(s.args, { userId: "kx99scoped" });
delete process.env.USER_ID;
s = claimSpec();
assert.equal(s.path, "messages:claimNextAny");

console.log("scoped self-check PASS");
