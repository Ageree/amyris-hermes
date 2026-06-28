// Self-check for the drainer's durable-facts machinery (offline, deterministic).
// Uses a throwaway DRAINER_FACTS_FILE set BEFORE a dynamic import (FACTS_FILE is read at
// module load). Run (env sourced so the module's top-level checks pass):
//   node control-plane/drainer/facts.test.mjs
import assert from "node:assert";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { rmSync } from "node:fs";

const FACTS = join(tmpdir(), `drainer-facts-test-${process.pid}.json`);
process.env.DRAINER_FACTS_FILE = FACTS;

try {
  const { extractMemories, buildMessage, factsFor, addFact } = await import("./drainer.mjs");

  // extractMemories: pull markers, strip from user-facing text.
  {
    const { cleaned, memories } = extractMemories("привет! [[remember:живёт в москве]] рад помочь");
    assert.deepEqual(memories, ["живёт в москве"]);
    assert.ok(!cleaned.includes("[[remember"), "marker stripped from reply");
    assert.ok(cleaned.includes("привет") && cleaned.includes("рад помочь"), "surrounding text kept");
  }
  {
    const { memories } = extractMemories("[[remember:любит суши]]ок[[remember:аллергия на орехи]]");
    assert.deepEqual(memories, ["любит суши", "аллергия на орехи"], "multiple markers");
  }
  {
    const { cleaned, memories } = extractMemories("обычный ответ без маркеров");
    assert.equal(cleaned, "обычный ответ без маркеров");
    assert.equal(memories.length, 0);
  }

  // buildMessage: facts block + history + current message, in order.
  {
    const m = buildMessage([{ text: "привет", reply: "здравствуй" }], ["живёт в москве"], "что закажем?");
    assert.ok(m.includes("что ты уже знаешь"), "facts header");
    assert.ok(m.includes("- живёт в москве"), "fact listed");
    assert.ok(m.includes("недавний контекст"), "history block");
    assert.ok(m.trim().endsWith("что закажем?"), "current message last");
  }
  assert.equal(buildMessage([], [], "хай"), "хай", "no facts/history → bare text");
  assert.ok(buildMessage([], ["город москва"], "хай").includes("- город москва"), "facts-only still injects");

  // addFact / factsFor: exact dedup + per-key isolation + persistence to disk.
  addFact("u1", "любит пиццу");
  addFact("u1", "любит пиццу"); // exact dup → ignored
  addFact("u1", "  город москва  "); // trimmed
  assert.deepEqual(factsFor("u1"), ["любит пиццу", "город москва"]);
  assert.deepEqual(factsFor("u2"), [], "facts are isolated per user key");
  addFact("u2", "");        // empty fact → ignored
  addFact("", "что-то");    // empty key → ignored
  assert.deepEqual(factsFor("u2"), []);

  console.log("facts self-check PASS");
} finally {
  rmSync(FACTS, { force: true });
}
