// Self-check for the drainer's rich-message parser (offline, deterministic). Ports the
// load-bearing cases from lab/tests/test_rich.py — the contract the drainer renders.
// Run (env sourced so the module's top-level checks pass):
//   node control-plane/drainer/rich.test.mjs
import assert from "node:assert";
import { parseRich, emojiToTapback } from "./drainer.mjs";

const types = (r) => r.map((p) => p.t);

// 1. Plain reply → exactly one text part (back-compat with the old plain send).
{
  const r = parseRich("привет, всё ок");
  assert.deepEqual(types(r), ["text"]);
  assert.equal(r[0].text, "привет, всё ок");
}

// 2. Leading reaction(s) peel off, in order, before the text.
{
  const r = parseRich("[[react:❤️]]рад тебя слышать");
  assert.deepEqual(types(r), ["react", "text"]);
  assert.equal(r[0].emoji, "❤️");
  assert.equal(r[1].text, "рад тебя слышать");
}

// 3. A bare http(s) image URL → image part; surrounding text preserved in order.
{
  const r = parseRich("вот картинка https://x.test/cat.png смотри");
  assert.deepEqual(types(r), ["text", "image", "text"]);
  assert.equal(r[1].src, "https://x.test/cat.png");
}

// 4. Markdown image → image.
{
  const r = parseRich("![cat](https://x.test/cat.jpg)");
  assert.deepEqual(types(r), ["image"]);
  assert.equal(r[0].src, "https://x.test/cat.jpg");
}

// 5. A markdown LINK whose URL ends in an image extension stays TEXT (not shredded).
{
  const r = parseRich("see [the photo](https://x.test/banner.png) here");
  assert.deepEqual(types(r), ["text"]);
  assert.ok(r[0].text.includes("https://x.test/banner.png"));
}

// 6. A non-image URL is left inline as text (iMessage auto-unfurls it).
{
  const r = parseRich("открой https://news.ycombinator.com сейчас");
  assert.deepEqual(types(r), ["text"]);
}

// 7. A fenced poll → poll part (question + options).
{
  const r = parseRich("```poll\nКуда?\nДомой\nВ офис\n```");
  assert.deepEqual(types(r), ["poll"]);
  assert.equal(r[0].question, "Куда?");
  assert.deepEqual(r[0].options, ["Домой", "В офис"]);
}

// 8. emoji → tapback mapping (and the skip path).
assert.equal(emojiToTapback("❤️"), "love");
assert.equal(emojiToTapback("👍"), "like");
assert.equal(emojiToTapback("🔥"), "emphasize");
assert.equal(emojiToTapback("love"), "love"); // literal tapback word passes through
assert.equal(emojiToTapback("🦄"), null); // unmappable → skip (caller drops it)

console.log("rich self-check PASS");
