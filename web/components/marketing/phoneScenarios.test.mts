// Lazy self-check for the showcase state-machine. Run: node phoneScenarios.test.mts
import assert from "node:assert/strict";
import { SCENARIOS, advance, stepDelay, FINAL_STEP } from "./phoneScenarios.ts";

const N = SCENARIOS.length;
assert.equal(N, 10, "expected 10 scenarios");

// every scenario is well-formed
for (const s of SCENARIOS) {
  assert.ok(s.user && s.reply && s.work, "scenario text fields present");
  assert.ok(["file", "table", "checklist", "card"].includes(s.rich.kind), "known rich kind");
}

// within a scenario, steps climb 0 → FINAL_STEP
let st = { idx: 0, step: 0 };
for (let i = 0; i < FINAL_STEP; i++) st = advance(st, N);
assert.deepEqual(st, { idx: 0, step: FINAL_STEP }, "climbs to final step in place");

// at FINAL_STEP it wraps to the next scenario's step 0
assert.deepEqual(advance({ idx: 0, step: FINAL_STEP }, N), { idx: 1, step: 0 }, "advances scenario");

// the last scenario loops back to the first
assert.deepEqual(advance({ idx: N - 1, step: FINAL_STEP }, N), { idx: 0, step: 0 }, "loops");

// a full run of every step over every scenario returns home — proves no dead state
let cur = { idx: 0, step: 0 };
for (let i = 0; i < N * (FINAL_STEP + 1); i++) cur = advance(cur, N);
assert.deepEqual(cur, { idx: 0, step: 0 }, "full cycle returns to start");

// delays are positive and the hold (final) is the longest
for (let s = 0; s <= FINAL_STEP; s++) assert.ok(stepDelay(s) > 0, "positive delay");
assert.ok(stepDelay(FINAL_STEP) > stepDelay(2), "rich answer holds longest");

console.log("phoneScenarios: all checks passed ✓");
