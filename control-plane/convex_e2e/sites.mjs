// Live end-to-end for the chat-sites feature. Runs against the configured dev
// deployment (zany-tapir-501). Proves: publish static -> serve; publish app ->
// serve + Turso-backed insert/select via the data proxy; and the trust-boundary
// rejections (bad handle, wrong worker secret, ATTACH, data on a static site).
// Cleans up the provisioned Turso databases at the end (no probe junk).
//
//   CONVEX_URL=...cloud CONVEX_SITE_URL=...site SITES_PUBLISH_SECRET=... \
//   TURSO_PLATFORM_TOKEN=... node control-plane/convex_e2e/sites.mjs
//
// Exit 0 = all assertions PASS.

const CLOUD = need("CONVEX_URL");
const SITE = need("CONVEX_SITE_URL");
const SECRET = need("SITES_PUBLISH_SECRET");
const TURSO = process.env.TURSO_PLATFORM_TOKEN || "";
const ORG = process.env.TURSO_ORG || "ageree";

function need(name) {
  const v = process.env[name];
  if (!v) {
    console.error(`missing env ${name}`);
    process.exit(2);
  }
  return v.replace(/\/+$/, "");
}

let passed = 0;
const failures = [];
function ok(label) { passed++; console.log(`  PASS  ${label}`); }
function check(cond, label, extra) {
  if (cond) ok(label);
  else { failures.push(label); console.log(`  FAIL  ${label}${extra ? "  :: " + extra : ""}`); }
}

async function callAction(path, args) {
  const r = await fetch(`${CLOUD}/api/action`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path, args, format: "json" }),
  });
  const body = await r.json();
  return body; // { status: "success"|"error", value?, errorMessage? }
}

const rand = Date.now().toString(36);
const staticHandle = `e2e-static-${rand}`;
const appHandle = `e2e-app-${rand}`;
const STATIC_MARKER = `static-marker-${rand}`;
const APP_MARKER = `app-marker-${rand}`;

async function main() {
  console.log(`[chat-sites e2e] deployment ${SITE}`);

  // --- 1. publish STATIC ---------------------------------------------------
  const staticHtml = `<!doctype html><html><head><title>x</title></head><body><h1>${STATIC_MARKER}</h1></body></html>`;
  const pubStatic = await callAction("sites:publish", {
    secret: SECRET, handle: staticHandle, kind: "static", html: staticHtml, title: "e2e static",
  });
  check(pubStatic.status === "success", "publish static returns success", JSON.stringify(pubStatic).slice(0, 200));
  const staticUrl = pubStatic.value?.url;
  check(staticUrl === `${SITE}/s/${staticHandle}`, "static url is correct", staticUrl);

  // --- 2. serve STATIC -----------------------------------------------------
  {
    const r = await fetch(`${SITE}/s/${staticHandle}`);
    const html = await r.text();
    check(r.status === 200, "GET static -> 200", String(r.status));
    check((r.headers.get("content-type") || "").includes("text/html"), "static content-type text/html");
    check(html.includes(STATIC_MARKER), "static body contains marker");
    check(!html.includes("window.dbQuery"), "static has NO db runtime injected");
  }

  // --- 3. publish APP (guestbook, Turso) -----------------------------------
  const schema = `CREATE TABLE IF NOT EXISTS guest(id integer primary key autoincrement, name text not null, msg text, ts integer);`;
  const appHtml = `<!doctype html><html><head><meta charset=utf-8><title>guestbook</title></head><body><h1>${APP_MARKER}</h1><div id=app>uses dbQuery</div></body></html>`;
  const pubApp = await callAction("sites:publish", {
    secret: SECRET, handle: appHandle, kind: "app", html: appHtml, schema, title: "e2e guestbook",
  });
  check(pubApp.status === "success", "publish app returns success (provisions Turso)", JSON.stringify(pubApp).slice(0, 300));
  check(pubApp.value?.url === `${SITE}/s/${appHandle}`, "app url is correct", pubApp.value?.url);

  // --- 4. serve APP (runtime injected) -------------------------------------
  {
    const r = await fetch(`${SITE}/s/${appHandle}`);
    const html = await r.text();
    check(r.status === 200, "GET app -> 200");
    check(html.includes(APP_MARKER), "app body contains marker");
    check(html.includes("window.dbQuery"), "app HAS db runtime injected");
    check(html.includes(`/site-data/${appHandle}`), "app runtime points at its data proxy");
  }

  // --- 5. data proxy: INSERT then SELECT -----------------------------------
  async function data(handle, sql, args) {
    const r = await fetch(`${SITE}/site-data/${handle}`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ sql, args: args || [] }),
    });
    return { status: r.status, body: await r.json() };
  }
  {
    const ins = await data(appHandle, "INSERT INTO guest(name,msg,ts) VALUES (?,?,?)", ["Saveliy", "hi from e2e", 1750000000]);
    check(ins.status === 200 && ins.body.rowsAffected === 1, "data INSERT affected 1 row", JSON.stringify(ins).slice(0, 200));
    const sel = await data(appHandle, "SELECT id,name,msg FROM guest ORDER BY id", []);
    check(sel.status === 200, "data SELECT -> 200");
    check(Array.isArray(sel.body.rows) && sel.body.rows.length >= 1, "SELECT returns >=1 row");
    check(sel.body.rows?.[0]?.name === "Saveliy", "SELECT row has name=Saveliy", JSON.stringify(sel.body).slice(0, 200));
  }

  // --- 6. trust boundaries -------------------------------------------------
  {
    const bad = await callAction("sites:publish", { secret: SECRET, handle: "a", kind: "static", html: "<h1>x</h1>" });
    check(bad.status === "error", "publish bad handle 'a' rejected", JSON.stringify(bad).slice(0, 150));

    const wrong = await callAction("sites:publish", { secret: "WRONG", handle: `e2e-x-${rand}`, kind: "static", html: "<h1>x</h1>" });
    check(wrong.status === "error" && /unauthorized publisher/.test(wrong.errorMessage || ""), "publish wrong publish secret rejected", JSON.stringify(wrong).slice(0, 150));

    const attach = await data(appHandle, "ATTACH DATABASE 'other.db' AS o", []);
    check(attach.status === 400 && /ATTACH/i.test(attach.body.error || ""), "data ATTACH rejected (400)", JSON.stringify(attach).slice(0, 150));

    const onStatic = await data(staticHandle, "SELECT 1", []);
    check(onStatic.status === 400 && /no data backend/.test(onStatic.body.error || ""), "data on static site rejected (400)", JSON.stringify(onStatic).slice(0, 150));

    const missing = await fetch(`${SITE}/s/does-not-exist-${rand}`);
    check(missing.status === 404, "GET unknown handle -> 404");
  }

  // --- 7. cleanup provisioned Turso DBs (no probe junk) --------------------
  if (TURSO) {
    const list = await fetch(`https://api.turso.tech/v1/organizations/${ORG}/databases`, {
      headers: { authorization: `Bearer ${TURSO}` },
    }).then((r) => r.json()).catch(() => ({}));
    const dbs = (list.databases || []).map((d) => d.Name || d.name).filter((n) => n && n.startsWith(`s-${appHandle}`));
    for (const name of dbs) {
      const dr = await fetch(`https://api.turso.tech/v1/organizations/${ORG}/databases/${name}`, {
        method: "DELETE", headers: { authorization: `Bearer ${TURSO}` },
      });
      console.log(`  cleanup  deleted turso db ${name} (HTTP ${dr.status})`);
    }
  } else {
    console.log("  cleanup  TURSO_PLATFORM_TOKEN not provided -> skipped db delete");
  }

  console.log(`\n[chat-sites e2e] ${passed} passed, ${failures.length} failed`);
  if (failures.length) { console.log("FAILED:", failures.join(" | ")); process.exit(1); }
  console.log("ALL PASS");
}

main().catch((e) => { console.error("e2e crashed:", e); process.exit(1); });
