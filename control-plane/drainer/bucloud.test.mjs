// Self-check for the browser-use cloud client: asserts the request SHAPE (endpoint, auth
// header, profileId/customProxy wiring) and response parsing against a FAKE local server —
// no real BU account/key needed. Run: node control-plane/drainer/bucloud.test.mjs
import assert from "node:assert";
import http from "node:http";

// Fake BU cloud: records each request, returns canned responses by method+path.
const seen = [];
const server = http.createServer((req, res) => {
  let body = "";
  req.on("data", (d) => (body += d));
  req.on("end", () => {
    seen.push({ method: req.method, path: req.url, auth: req.headers["x-browser-use-api-key"], body: body ? JSON.parse(body) : null });
    res.setHeader("content-type", "application/json");
    if (req.method === "POST" && req.url === "/profiles") return res.end(JSON.stringify({ id: "prof-123" }));
    if (req.method === "POST" && req.url === "/browsers") {
      return res.end(JSON.stringify({ id: "sess-9", cdpUrl: "https://cdp.browser-use.com/sess-9", liveUrl: "https://live.browser-use.com/sess-9?ws=x" }));
    }
    if (req.method === "PATCH" && /^\/browsers\//.test(req.url)) return res.end(JSON.stringify({ ok: true }));
    res.statusCode = 404; res.end("{}");
  });
});

await new Promise((r) => server.listen(0, "127.0.0.1", r));
const port = server.address().port;
process.env.BU_CLOUD_BASE = `http://127.0.0.1:${port}`;
process.env.BU_CLOUD_API_KEY = "test-key";
// import AFTER env is set (module reads BU_BASE/BU_KEY at load).
const { createProfile, startBrowser, stopBrowser, buildBrowserBody, getOrCreateProfile, openForUser } =
  await import("./bucloud.mjs");

// 1. createProfile → POST /profiles {name}, auth header carried, returns id.
const pid = await createProfile("user-+79990000000");
assert.equal(pid, "prof-123");
let last = seen.at(-1);
assert.equal(last.method, "POST"); assert.equal(last.path, "/profiles");
assert.equal(last.auth, "test-key", "X-Browser-Use-API-Key must be sent");
assert.equal(last.body.name, "user-+79990000000");

// 2. startBrowser WITH a BYO RU proxy → customProxy in body, profileId carried, parses cdp+live.
const s = await startBrowser({ profileId: pid, proxy: { host: "ru.modem", port: 8080, username: "u", password: "p" }, timeoutSec: 300 });
assert.deepEqual({ id: s.id, cdpUrl: s.cdpUrl }, { id: "sess-9", cdpUrl: "https://cdp.browser-use.com/sess-9" });
assert.ok(s.liveUrl.startsWith("https://live.browser-use.com/"), "liveUrl for handoff");
last = seen.at(-1);
assert.equal(last.path, "/browsers");
assert.equal(last.body.profileId, "prof-123");
assert.deepEqual(last.body.customProxy, { host: "ru.modem", port: 8080, username: "u", password: "p" });
assert.equal(last.body.timeout, 300);
assert.ok(!("proxyCountryCode" in last.body), "BYO proxy → no native country code");

// 3. buildBrowserBody is pure & branches correctly (proxy vs no-proxy).
assert.deepEqual(buildBrowserBody({ profileId: "p", proxy: { host: "h", port: 1 }, timeoutSec: 600 }),
  { timeout: 600, profileId: "p", customProxy: { host: "h", port: 1 } });
const noProxy = buildBrowserBody({ profileId: "p", proxy: null, timeoutSec: 600 });
assert.equal(noProxy.proxyCountryCode, null);
assert.ok(!("customProxy" in noProxy), "no proxy → no customProxy");

// 4. stopBrowser → PATCH /browsers/{id} {action:"stop"}.
await stopBrowser("sess-9");
last = seen.at(-1);
assert.equal(last.method, "PATCH"); assert.equal(last.path, "/browsers/sess-9");
assert.equal(last.body.action, "stop");

// 5. getOrCreateProfile: FIRST call POSTs /profiles and persists; second call is a pure
// cache hit (no new network) — one BU profile per user, ever.
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
const profFile = join(mkdtempSync(join(tmpdir(), "bucloud-test-")), "profiles.json");
const before = seen.length;
const p1 = await getOrCreateProfile("+79990000000", profFile);
assert.equal(p1, "prof-123");
assert.equal(seen.length, before + 1, "first resolve creates the profile");
const p2 = await getOrCreateProfile("+79990000000", profFile);
assert.equal(p2, "prof-123");
assert.equal(seen.length, before + 1, "second resolve is a cache hit — no network");

// 6. openForUser: profile resolve (cached) + browser bound to it; returns cdp+live+profileId.
const sess = await openForUser("+79990000000", { timeoutSec: 300, proxy: null, file: profFile });
assert.equal(sess.profileId, "prof-123");
assert.equal(sess.cdpUrl, "https://cdp.browser-use.com/sess-9");
assert.ok(sess.liveUrl, "liveUrl present for handoff");
last = seen.at(-1);
assert.equal(last.path, "/browsers");
assert.equal(last.body.profileId, "prof-123", "browser is bound to the user's profile");
assert.equal(last.body.timeout, 300);

// 7. empty userKey is a hard error (never mint an anonymous shared profile).
await assert.rejects(() => getOrCreateProfile("", profFile), /empty userKey/);

server.close();
console.log("bucloud self-check PASS");
