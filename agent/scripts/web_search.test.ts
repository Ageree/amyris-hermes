import assert from "node:assert/strict";
import test from "node:test";

import { buildExaRequest, EXA_SEARCH_URL, parseExaResults } from "../agent/lib/exa.ts";

void test("buildExaRequest trims queries and clamps requested results", () => {
  const req = buildExaRequest("  погода в москве  ", 999, "test-key-123");

  assert.equal(req.url, EXA_SEARCH_URL);
  assert.equal(req.method, "POST");
  assert.equal(req.headers["x-api-key"], "test-key-123");
  assert.equal(req.headers["content-type"], "application/json");

  const body = JSON.parse(req.body);
  assert.equal(body.query, "погода в москве");
  assert.equal(body.numResults, 25);
  assert.equal(body.type, "auto");
  assert.ok(body.contents?.highlights);

  assert.equal(JSON.parse(buildExaRequest("x", 0, "k").body).numResults, 1);
  assert.throws(() => buildExaRequest("   ", 5, "k"), /non-empty/);
});

void test("parseExaResults normalizes result snippets and drops malformed entries", () => {
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

  assert.deepEqual(parsed[0], {
    title: "Foo",
    url: "https://a.test",
    snippet: "one ... two",
    published: "2026-01-01",
  });
  assert.equal(parsed.length, 2);
  assert.equal(parsed[1].title, "https://b.test");
  assert.equal(parsed[1].snippet, "body text here");
  assert.equal(parsed[1].published, null);
  assert.deepEqual(parseExaResults({}), []);
  assert.deepEqual(parseExaResults(null), []);
});
