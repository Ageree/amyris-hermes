// Network-free unit check for the web_search tool's request/response shaping.
// Run with Node 24 (strips TS types natively):  node scripts/web_search.check.ts
// Lives outside agent/ (not an eve slot) and outside tsconfig include — it's a
// runnable check, not part of the build.
import assert from "node:assert/strict";
import {
  buildExaRequest,
  parseExaResults,
  EXA_SEARCH_URL,
} from "../agent/lib/exa.ts";

// 1. request shape: trimmed query, key header, POST to the Exa search URL.
const req = buildExaRequest("  погода в москве  ", 3, "test-key-123");
assert.equal(req.url, EXA_SEARCH_URL);
assert.equal(req.method, "POST");
assert.equal(req.headers["x-api-key"], "test-key-123");
assert.equal(req.headers["content-type"], "application/json");
const body = JSON.parse(req.body);
assert.equal(body.query, "погода в москве"); // trimmed
assert.equal(body.numResults, 3);
assert.equal(body.type, "auto");
assert.ok(body.contents?.highlights, "highlights requested");

// 2. numResults clamps to 1..25.
assert.equal(JSON.parse(buildExaRequest("x", 999, "k").body).numResults, 25);
assert.equal(JSON.parse(buildExaRequest("x", 0, "k").body).numResults, 1);

// 3. empty query is rejected at the boundary.
assert.throws(() => buildExaRequest("   ", 5, "k"), /non-empty/);

// 4. response parsing: highlights joined, url-less dropped, empty title -> url.
const parsed = parseExaResults({
  results: [
    {
      title: "Foo",
      url: "https://a.test",
      highlights: ["one", "two"],
      publishedDate: "2026-01-01",
    },
    { title: "", url: "https://b.test", text: "body text here" },
    { title: "no url", url: "" },
  ],
});
assert.equal(parsed.length, 2, "the url-less result is dropped");
assert.deepEqual(parsed[0], {
  title: "Foo",
  url: "https://a.test",
  snippet: "one ... two",
  published: "2026-01-01",
});
assert.equal(parsed[1].title, "https://b.test"); // empty title falls back to url
assert.equal(parsed[1].snippet, "body text here");
assert.equal(parsed[1].published, null);

// 5. malformed / non-array input -> empty list (never throws).
assert.deepEqual(parseExaResults({}), []);
assert.deepEqual(parseExaResults(null), []);

console.log("web_search shaping check: PASS");
