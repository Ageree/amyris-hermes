// browser-use cloud client — the per-user multitenancy layer. Provisions a cloud Chrome
// bound to ONE user's persistent profile (their Yandex login + their linked card live in
// the profile's cookies, NOT in our infra) + a BYO RU proxy, and hands back:
//   • cdpUrl  → order.py attaches to it (ORDER_CDP_URL) — SAME engine, cloud instead of :9333
//   • liveUrl → handoff: when the agent hits login / SMS-OTP / 3DS / captcha (which it must
//               NOT do itself), we send the user this URL; they act in the SAME live session,
//               the profile persists, and future orders just run.
//
// API verified 2026-06-28 from browser-use CLOUD.md:
//   POST  /api/v2/profiles            {name?}                       -> {id}
//   POST  /api/v2/browsers            {profileId?,customProxy?,proxyCountryCode?,timeout?}
//                                                                    -> {id,cdpUrl,liveUrl}
//   PATCH /api/v2/browsers/{id}       {action:"stop"}               -> (refunds unused time)
// Native proxyCountryCode enum is us/uk/fr/it/jp/au/de/fi/ca/in — NO `ru`, so a RU session
// REQUIRES a BYO `customProxy` (a mobileproxy.space modem). Pure HTTP, no deps.
//
// ponytail: a SINGLE RU modem from env (one sticky IP). Ceiling = one concurrent Yandex
// order at a time (Yandex anti-bot 403s concurrent sessions per IP — see gotcha). Upgrade =
// a modem POOL sized to peak concurrency + sticky-allocate per order (cloud-browser-decision.md).

const BU_BASE = (process.env.BU_CLOUD_BASE || "https://api.browser-use.com/api/v2").replace(/\/+$/, "");
const BU_KEY = process.env.BU_CLOUD_API_KEY || "";
const BU_TIMEOUT_MS = Number(process.env.BU_CLOUD_HTTP_TIMEOUT_MS || 30000);

// One RU modem (BYO). Prod swaps this for a pool allocator. Empty host → no customProxy
// (dev only: BU has no RU native exit, so a real RU order needs this set).
function ruProxyFromEnv() {
  const host = process.env.BU_PROXY_HOST || "";
  if (!host) return null;
  return {
    host,
    port: Number(process.env.BU_PROXY_PORT || 0),
    username: process.env.BU_PROXY_USERNAME || undefined,
    password: process.env.BU_PROXY_PASSWORD || undefined,
  };
}

async function bu(method, path, body) {
  if (!BU_KEY) throw new Error("BU_CLOUD_API_KEY not set");
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), BU_TIMEOUT_MS);
  try {
    const res = await fetch(`${BU_BASE}${path}`, {
      method,
      headers: { "content-type": "application/json", "X-Browser-Use-API-Key": BU_KEY },
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      throw new Error(`bucloud ${method} ${path} HTTP ${res.status}: ${JSON.stringify(data)?.slice(0, 200)}`);
    }
    return data;
  } finally {
    clearTimeout(t);
  }
}

// Create a persistent per-user profile (ONCE per user). Returns the profileId to store.
async function createProfile(name) {
  const d = await bu("POST", "/profiles", name ? { name } : {});
  const id = d?.id;
  if (!id) throw new Error("bucloud createProfile: no id in response");
  return id;
}

// Start a cloud browser bound to the user's profile + a BYO RU proxy. Returns the bits the
// caller needs: the session id (to stop), cdpUrl (for order.py), liveUrl (for handoff).
async function startBrowser({ profileId, proxy = ruProxyFromEnv(), timeoutSec = 600 } = {}) {
  const body = { timeout: timeoutSec };
  if (profileId) body.profileId = profileId;
  if (proxy?.host) body.customProxy = proxy; // BYO RU modem (preferred for Yandex)
  else body.proxyCountryCode = null; // no RU native; null = no BU proxy (dev fallback only)
  const d = await bu("POST", "/browsers", body);
  if (!d?.cdpUrl) throw new Error("bucloud startBrowser: no cdpUrl in response");
  return { id: d.id, cdpUrl: d.cdpUrl, liveUrl: d.liveUrl || null };
}

// Stop a session (refunds unused time). Best-effort — never throw on cleanup.
async function stopBrowser(id) {
  if (!id) return;
  try { await bu("PATCH", `/browsers/${id}`, { action: "stop" }); }
  catch { /* best-effort cleanup */ }
}

// Build the per-order request body WITHOUT calling the network — pure, so the wiring
// (profileId + BYO-proxy vs native-country branch) is unit-checkable offline.
function buildBrowserBody({ profileId, proxy, timeoutSec = 600 }) {
  const body = { timeout: timeoutSec };
  if (profileId) body.profileId = profileId;
  if (proxy?.host) body.customProxy = proxy;
  else body.proxyCountryCode = null;
  return body;
}

export { createProfile, startBrowser, stopBrowser, buildBrowserBody, ruProxyFromEnv, bu };
