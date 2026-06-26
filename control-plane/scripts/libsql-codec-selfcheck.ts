// Offline self-check for the libSQL value codec (convex/lib/libsql.ts). The network
// paths need a live Turso DB, but the encode/decode codec is pure — and its int-vs-
// float distinction is load-bearing (a whole JS number MUST encode as an integer so
// `id = ?` / `created_at >= ?` compare against INTEGER columns correctly).
//
// Run (no deps, Node ≥ 22.6): node --experimental-strip-types \
//   control-plane/scripts/libsql-codec-selfcheck.ts
import assert from "node:assert/strict";
import { __codec } from "../convex/lib/libsql.ts";

const { encodeArg, decodeCell } = __codec;

// --- encode ----------------------------------------------------------------
assert.deepEqual(encodeArg(null), { type: "null" });
assert.deepEqual(encodeArg(undefined), { type: "null" });
assert.deepEqual(encodeArg(true), { type: "integer", value: "1" });
assert.deepEqual(encodeArg(false), { type: "integer", value: "0" });
// whole numbers → integer (NOT float) — the correctness point
assert.deepEqual(encodeArg(5), { type: "integer", value: "5" });
assert.deepEqual(encodeArg(1719446400000), { type: "integer", value: "1719446400000" });
assert.deepEqual(encodeArg(10n), { type: "integer", value: "10" });
assert.deepEqual(encodeArg(3.14), { type: "float", value: 3.14 });
assert.deepEqual(encodeArg("привычка"), { type: "text", value: "привычка" });
assert.deepEqual(encodeArg(new Uint8Array([1, 2, 3])), {
  type: "blob",
  base64: btoa("\x01\x02\x03"),
});

// --- decode ----------------------------------------------------------------
assert.equal(decodeCell({ type: "null" }), null);
assert.equal(decodeCell({ type: "integer", value: "42" }), 42);
assert.equal(decodeCell({ type: "float", value: 1.5 }), 1.5);
assert.equal(decodeCell({ type: "text", value: "x" }), "x");

// --- round-trips -----------------------------------------------------------
assert.equal(decodeCell(encodeArg(7)), 7);
assert.equal(decodeCell(encodeArg("hi")), "hi");
const bytes = new Uint8Array([0, 255, 16, 32]);
assert.deepEqual(decodeCell(encodeArg(bytes)), bytes);

console.log("libsql codec self-check: OK");
