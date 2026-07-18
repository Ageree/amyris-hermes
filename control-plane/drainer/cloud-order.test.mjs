// Self-check for the per-user cloud-browser order lifecycle (offline, deterministic).
// Pins the money-and-handoff logic of execOrderEngine + appendCloudHandoff with injected
// fakes: session opened per user, engine gets the session's cdpUrl, stop-on-finish
// (= the pay-per-use refund), keep-alive + live_url handoff on login/3DS walls, local
// fallback when the cloud is down. Run: node control-plane/drainer/cloud-order.test.mjs
import assert from "node:assert";
import { execOrderEngine, appendCloudHandoff, HANDOFF_NEEDS } from "./drainer.mjs";

const SESSION = {
  id: "sess-1",
  cdpUrl: "wss://cdp.bu/sess-1",
  liveUrl: "https://live.bu/sess-1",
  profileId: "prof-1",
};

function makeDeps(results, { openFails = false } = {}) {
  const calls = { open: [], exec: [], stop: [], log: [] };
  let i = 0;
  return {
    calls,
    deps: {
      enabled: true,
      timeoutSec: 600,
      log: (...a) => calls.log.push(a.join(" ")),
      open: async (userKey, opts) => {
        calls.open.push({ userKey, opts });
        if (openFails) throw new Error("bu down");
        return { ...SESSION };
      },
      stop: async (id) => calls.stop.push(id),
      exec: async (service, params, cdp) => {
        calls.exec.push({ service, params, cdp });
        const r = results[Math.min(i, results.length - 1)];
        i += 1;
        return r;
      },
    },
  };
}

// --- 1. happy path: session per user, engine on its cdpUrl, stopped after (refund) ---
{
  const { calls, deps } = makeDeps([{ ok: true, final_result: "корзина 113₽" }]);
  const out = await execOrderEngine("food", { address: "Тверская 7", item: "бургер" }, "user-1", deps);
  assert.equal(calls.open.length, 1);
  assert.deepEqual(calls.open[0], { userKey: "user-1", opts: { timeoutSec: 600 } });
  assert.equal(calls.exec.length, 1, "success → no retry");
  assert.equal(calls.exec[0].cdp, SESSION.cdpUrl, "engine attaches to the CLOUD session");
  assert.deepEqual(calls.stop, ["sess-1"], "session stopped right after → unused time refunded");
  assert.equal(out.keptAlive, false);
  assert.equal(out.res.ok, true);
}

// --- 2. login wall: session KEPT ALIVE, reply carries its live_url ---
{
  const { calls, deps } = makeDeps([{ ok: false, status: "incomplete", needs: "NEED_LOGIN", final_result: "NEED_LOGIN" }]);
  const out = await execOrderEngine("food", { address: "x", item: "y" }, "user-1", deps);
  assert.equal(calls.stop.length, 0, "login handoff → session must stay alive for the user");
  assert.equal(calls.exec.length, 1, "a `needs` wall is NEVER retried (burns paid minutes)");
  assert.equal(out.keptAlive, true);

  const reply = appendCloudHandoff("нужно войти", out.res, out.session, 600);
  assert.ok(reply.includes(SESSION.liveUrl), "reply carries the live session URL");
  assert.ok(reply.includes("войди в Яндекс"), "login wording");
  assert.ok(reply.includes("~10 мин"), "session lifetime surfaced from timeoutSec");
}

// --- 3. 3DS wall: kept alive, 3-D Secure wording ---
{
  const { deps } = makeDeps([{ ok: false, status: "incomplete", needs: "NEED_3DS", final_result: "NEED_3DS" }]);
  const out = await execOrderEngine("food", { address: "x", item: "y" }, "user-1", deps);
  assert.equal(out.keptAlive, true);
  const reply = appendCloudHandoff("банк просит код", out.res, out.session, 600);
  assert.ok(reply.includes("3-D Secure") && reply.includes(SESSION.liveUrl));
}

// --- 4. NEED_CARD is NOT a live-session handoff: stop for the refund ---
{
  const { calls, deps } = makeDeps([{ ok: false, status: "incomplete", needs: "NEED_CARD", final_result: "NEED_CARD" }]);
  const out = await execOrderEngine("food", { address: "x", item: "y" }, "user-1", deps);
  assert.deepEqual(calls.stop, ["sess-1"], "card-missing → nothing to do live, refund");
  assert.equal(out.keptAlive, false);
  assert.equal(appendCloudHandoff("r", out.res, out.session), "r", "no live_url appended");
}

// --- 5. flaky failure (no `needs`): ONE retry on the SAME session ---
{
  const { calls, deps } = makeDeps([
    { ok: false, status: "failed" },
    { ok: true, final_result: "такси 250₽" },
  ]);
  const out = await execOrderEngine("taxi", { from: "А", to: "Б" }, "user-1", deps);
  assert.equal(calls.exec.length, 2, "one retry");
  assert.equal(calls.exec[1].cdp, SESSION.cdpUrl, "retry reuses the same paid session");
  assert.equal(calls.open.length, 1, "no second session opened");
  assert.deepEqual(calls.stop, ["sess-1"]);
  assert.equal(out.res.ok, true);
}

// --- 6. cloud down: local fallback (null cdp), orders keep working ---
{
  const { calls, deps } = makeDeps([{ ok: true, final_result: "ок" }], { openFails: true });
  const out = await execOrderEngine("food", { address: "x", item: "y" }, "user-1", deps);
  assert.equal(out.session, null);
  assert.equal(calls.exec[0].cdp, null, "fallback runs the local engine");
  assert.equal(calls.stop.length, 0);
  assert.ok(calls.log.some((l) => l.includes("falling back to local engine")));
  assert.equal(out.res.ok, true);
}

// --- 7. cloud disabled / no userKey: never opens a session ---
{
  const { calls, deps } = makeDeps([{ ok: true, final_result: "ок" }]);
  await execOrderEngine("food", { address: "x", item: "y" }, "user-1", { ...deps, enabled: false });
  assert.equal(calls.open.length, 0, "disabled → local engine only");
  const { calls: c2, deps: d2 } = makeDeps([{ ok: true, final_result: "ок" }]);
  await execOrderEngine("food", { address: "x", item: "y" }, "", d2);
  assert.equal(c2.open.length, 0, "no userKey → never mint an anonymous session");
}

// --- 8. engine crash: session still stopped (no leaked per-minute billing) ---
{
  const { calls, deps } = makeDeps([]);
  deps.exec = async () => {
    throw new Error("boom");
  };
  await assert.rejects(
    () => execOrderEngine("food", { address: "x", item: "y" }, "user-1", deps),
    /boom/,
  );
  assert.deepEqual(calls.stop, ["sess-1"], "crash path still refunds the session");
}

// --- 9. appendCloudHandoff guards ---
assert.equal(appendCloudHandoff("r", { needs: "NEED_LOGIN" }, null), "r", "no session → unchanged");
assert.equal(
  appendCloudHandoff("r", { needs: "NEED_LOGIN" }, { liveUrl: "" }),
  "r",
  "no liveUrl → unchanged",
);
assert.ok(HANDOFF_NEEDS.has("NEED_LOGIN") && HANDOFF_NEEDS.has("NEED_3DS") && !HANDOFF_NEEDS.has("NEED_CARD"));

console.log("cloud-order self-check PASS");
