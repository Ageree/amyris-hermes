// LIVE smoke of the per-user cloud-browser lifecycle against the REAL browser-use API.
// Needs BU_CLOUD_API_KEY in the env; costs ≈$0.003 upfront (timeoutSec 180 at PAYG
// $0.06/h) and refunds on the immediate stop. NOT a CI test (real key, real network) —
// run it on the deploy host after wiring the key:
//   source ~/.eve-drainer/eve.env && node control-plane/drainer/bucloud-smoke.mjs
// Proves: profile create+cache, session open (no proxy), CDP answers, stop → refund.
import { getOrCreateProfile, openForUser, stopBrowser, bu } from "./bucloud.mjs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

if (!process.env.BU_CLOUD_API_KEY) {
  console.error("BU_CLOUD_API_KEY not set — source the drainer env first");
  process.exit(1);
}
const PROFILES = join(mkdtempSync(join(tmpdir(), "bu-smoke-")), "profiles.json");
const USER = `smoke-${process.pid}`;
const log = (...a) => console.error(new Date().toISOString(), ...a);

// 1. profile: created once, cached on the second resolve
const p1 = await getOrCreateProfile(USER, PROFILES);
const p2 = await getOrCreateProfile(USER, PROFILES);
log("profile:", p1, "| cache-hit:", p1 === p2);

// 2. session bound to the profile, NO proxy (both proxy fields omitted)
const t0 = Date.now();
const s = await openForUser(USER, { timeoutSec: 180, proxy: null, file: PROFILES });
log(`session up in ${Date.now() - t0}ms: id=${s.id} profile=${s.profileId}`);
log("liveUrl:", s.liveUrl || "(none)");

// 3. CDP really answers: Browser.getVersion over the session's WebSocket (node 22+)
let cdpOk = false;
try {
  const ws = new globalThis.WebSocket(s.cdpUrl); // node 22+ global (eslint env lags it)
  const version = await new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("CDP timeout 15s")), 15000);
    ws.onopen = () => ws.send(JSON.stringify({ id: 1, method: "Browser.getVersion" }));
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id === 1) {
        clearTimeout(t);
        resolve(m.result);
      }
    };
    ws.onerror = () => {
      clearTimeout(t);
      reject(new Error("CDP ws error"));
    };
  });
  ws.close();
  cdpOk = true;
  log("CDP:", version?.product || "(no product)");
} catch (e) {
  log("CDP check FAILED:", e.message);
}

// 4. stop immediately → unused time refunded (the pay-per-use half of the contract)
await stopBrowser(s.id);
const after = await bu("GET", `/browsers/${s.id}`).catch((e) => ({ error: e.message }));
log("after stop: status =", after?.status ?? after?.error);

if (cdpOk && after?.status === "stopped") {
  log("SMOKE PASS");
} else {
  log("SMOKE FAILED — see above");
  process.exit(1);
}
