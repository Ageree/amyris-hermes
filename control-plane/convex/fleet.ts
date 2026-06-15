import { mutation, internalMutation, query, type MutationCtx } from "./_generated/server";
import { v } from "convex/values";
import { internal } from "./_generated/api";
import type { Id } from "./_generated/dataModel";
import { assertWorker, channelValidator } from "./lib/auth";

// ---------------------------------------------------------------------------
// fleet.ts (design §4) — the desired-state map the controller reconciles toward
// and the scoped worker heartbeats into. ONE agentInstances row per user
// (by_user). Every function is WORKER_SECRET-gated (A4): the controller and the
// scoped workers call these over HTTP, never an authed browser client. All reads
// are index-only (by_user / by_desired_status / by_status_heartbeat) — never a
// row-scan predicate. Atomic status transitions give at-most-once launch even
// if old+new controllers overlap during a cutover.
// ---------------------------------------------------------------------------

const RECONCILE_LIMIT = 500;          // bound a single reconcile read
const REAP_BATCH = 500;               // paginated reaper page size
const IDLE_TTL_FREE_MS = 30 * 60_000; // free containers reaped after 30 min idle ($0)

const fleetTier = v.union(v.literal("free"), v.literal("paid"));
const instanceStatus = v.union(
  v.literal("provisioning"),
  v.literal("running"),
  v.literal("stopping"),
  v.literal("stopped"),
  v.literal("error"),
);
const desiredState = v.union(v.literal("running"), v.literal("stopped"));

// Local literal types mirroring the validators above. Importing `internal` (for
// the self-referencing reapIdleInstances cron) makes fleet.ts part of a
// fleet→_generated/api→fleet type cycle, inside which `Doc<"agentInstances">`
// enum fields resolve to bare `string`. The rows are schema-constrained, so we
// narrow those fields to these aliases where they flow into validated returns.
type InstanceStatus = "provisioning" | "running" | "stopping" | "stopped" | "error";
type DesiredState = "running" | "stopped";
type FleetTier = "free" | "paid";

// ---------------------------------------------------------------------------
// requestInstance — cold-start. Inbound for a user with no warm container flips
// desired→running (upsert). Idempotent: an already-running/desired-running row is
// left as-is (only wantsAt is refreshed so the cold-start clock is accurate).
//
// Two entry points share requestInstanceImpl: the public `requestInstance`
// (WORKER_SECRET-gated, for the controller/admin/tests) and the internal
// `requestInstanceInternal` (called by the inbound webhooks in http.ts right
// after a tenant row is enqueued — wiring the cold-start edge so an idle/never-
// launched tenant's message actually triggers a launch instead of sitting in the
// queue). When the caller doesn't pin a tier, derive it from the user's
// entitlement (pro/max → "paid" stays warm; free/none → "free" is idle-reaped).
// ---------------------------------------------------------------------------
async function deriveTier(
  ctx: MutationCtx,
  userId: Id<"users">,
): Promise<FleetTier> {
  const ent = await ctx.db
    .query("entitlements")
    .withIndex("by_user", (q) => q.eq("userId", userId))
    .first();
  return ent && (ent.tier === "pro" || ent.tier === "max") ? "paid" : "free";
}

export async function requestInstanceImpl(
  ctx: MutationCtx,
  args: { userId: Id<"users">; tier?: FleetTier; channel?: "imessage" | "telegram" },
): Promise<{ instanceId: Id<"agentInstances">; status: InstanceStatus; created: boolean }> {
  const { userId, tier, channel } = args;
  const now = Date.now();
  const existing = await ctx.db
    .query("agentInstances")
    .withIndex("by_user", (q) => q.eq("userId", userId))
    .first();
  if (existing) {
    const patch: Record<string, unknown> = { wantsAt: now };
    if (existing.desired !== "running") patch.desired = "running";
    if (channel && existing.channel !== channel) patch.channel = channel;
    await ctx.db.patch(existing._id, patch);
    return {
      instanceId: existing._id,
      status: existing.status as InstanceStatus,
      created: false,
    };
  }
  const instanceId = await ctx.db.insert("agentInstances", {
    userId,
    channel,
    desired: "running",
    status: "provisioning",
    tier: tier ?? (await deriveTier(ctx, userId)),
    wantsAt: now,
  });
  return { instanceId, status: "provisioning" as InstanceStatus, created: true };
}

export const requestInstance = mutation({
  args: {
    workerSecret: v.string(),
    userId: v.id("users"),
    tier: v.optional(fleetTier),
    channel: v.optional(channelValidator),
  },
  returns: v.object({
    instanceId: v.id("agentInstances"),
    status: instanceStatus,
    created: v.boolean(),
  }),
  handler: async (ctx, { workerSecret, userId, tier, channel }) => {
    assertWorker(workerSecret);
    return await requestInstanceImpl(ctx, { userId, tier, channel });
  },
});

// Internal cold-start trigger for the inbound webhooks (http.ts). Not client-
// callable; no WORKER_SECRET (internal functions are unreachable over HTTP).
export const requestInstanceInternal = internalMutation({
  args: { userId: v.id("users"), channel: v.optional(channelValidator) },
  returns: v.object({
    instanceId: v.id("agentInstances"),
    status: instanceStatus,
    created: v.boolean(),
  }),
  handler: async (ctx, { userId, channel }) => {
    return await requestInstanceImpl(ctx, { userId, channel });
  },
});

// ---------------------------------------------------------------------------
// claimInstanceForLaunch — the controller calls this AFTER a successful docker
// run to record the live container. Atomic guard: only a non-running row can be
// claimed, so two controllers racing the same launch can't both win (the loser
// gets claimed:false and tears down its duplicate container).
// ---------------------------------------------------------------------------
export const claimInstanceForLaunch = mutation({
  args: {
    workerSecret: v.string(),
    userId: v.id("users"),
    hostVm: v.string(),
    containerId: v.string(),
    workerSecretRef: v.optional(v.string()),
  },
  returns: v.object({ claimed: v.boolean() }),
  handler: async (ctx, { workerSecret, userId, hostVm, containerId, workerSecretRef }) => {
    assertWorker(workerSecret);
    const instance = await ctx.db
      .query("agentInstances")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .first();
    if (!instance) return { claimed: false };
    if (instance.status === "running") return { claimed: false }; // already live — loser
    const now = Date.now();
    await ctx.db.patch(instance._id, {
      status: "running",
      hostVm,
      containerId,
      workerSecretRef: workerSecretRef ?? instance.workerSecretRef,
      startedAt: now,
      heartbeatAt: now,
      lastActiveAt: instance.lastActiveAt ?? now,
      errorCount: 0,
      error: undefined,
    });
    return { claimed: true };
  },
});

// ---------------------------------------------------------------------------
// heartbeat — the scoped worker writes this each poll loop. Returns the current
// desired state so a worker whose instance has been reaped (desired→stopped) can
// drain + exit gracefully instead of being SIGKILLed. Best-effort: a missing row
// (pre-fleet operator) is not an error.
// ---------------------------------------------------------------------------
export const heartbeat = mutation({
  args: { workerSecret: v.string(), userId: v.id("users") },
  returns: v.object({ desired: v.union(desiredState, v.null()) }),
  handler: async (ctx, { workerSecret, userId }) => {
    assertWorker(workerSecret);
    const instance = await ctx.db
      .query("agentInstances")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .first();
    if (!instance) return { desired: null };
    const patch: Record<string, unknown> = { heartbeatAt: Date.now() };
    if (instance.status === "provisioning") patch.status = "running";
    await ctx.db.patch(instance._id, patch);
    return { desired: instance.desired as DesiredState };
  },
});

// markStopped — controller after a clean `docker stop` (idle-reap or rebalance).
export const markStopped = mutation({
  args: { workerSecret: v.string(), userId: v.id("users") },
  returns: v.null(),
  handler: async (ctx, { workerSecret, userId }) => {
    assertWorker(workerSecret);
    const instance = await ctx.db
      .query("agentInstances")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .first();
    if (instance) {
      await ctx.db.patch(instance._id, {
        status: "stopped",
        stoppedAt: Date.now(),
        containerId: undefined,
        hostVm: undefined,
      });
    }
    return null;
  },
});

// markError — controller on a launch/health failure. Increments errorCount so the
// controller can alert + stop relaunch-storming after N consecutive failures.
export const markError = mutation({
  args: { workerSecret: v.string(), userId: v.id("users"), error: v.string() },
  returns: v.object({ errorCount: v.number() }),
  handler: async (ctx, { workerSecret, userId, error }) => {
    assertWorker(workerSecret);
    const instance = await ctx.db
      .query("agentInstances")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .first();
    if (!instance) return { errorCount: 0 };
    const errorCount = (instance.errorCount ?? 0) + 1;
    await ctx.db.patch(instance._id, { status: "error", error, errorCount });
    return { errorCount };
  },
});

// setDesired — flip the control-loop target. Idle-reaper sets "stopped"; an
// inbound for a stopped user sets "running" (refreshing the cold-start clock).
export const setDesired = mutation({
  args: { workerSecret: v.string(), userId: v.id("users"), desired: desiredState },
  returns: v.null(),
  handler: async (ctx, { workerSecret, userId, desired }) => {
    assertWorker(workerSecret);
    const instance = await ctx.db
      .query("agentInstances")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .first();
    if (instance) {
      const patch: Record<string, unknown> = { desired };
      if (desired === "running") patch.wantsAt = Date.now();
      await ctx.db.patch(instance._id, patch);
    }
    return null;
  },
});

const reconcileItem = v.object({
  instanceId: v.id("agentInstances"),
  userId: v.id("users"),
  desired: desiredState,
  status: instanceStatus,
  tier: fleetTier,
  hostVm: v.union(v.string(), v.null()),
  containerId: v.union(v.string(), v.null()),
  heartbeatAt: v.union(v.number(), v.null()),
  lastActiveAt: v.union(v.number(), v.null()),
  wantsAt: v.union(v.number(), v.null()),
  errorCount: v.number(),
});

// ---------------------------------------------------------------------------
// listReconcile — the controller's ~3s poll. Returns the actionable set: every
// instance that SHOULD be running (by_desired_status) unioned with every instance
// currently running (by_status_heartbeat, for health + idle checks). Index-only,
// bounded; dedup by _id in JS. The controller diffs desired vs actual and acts.
// ---------------------------------------------------------------------------
export const listReconcile = query({
  args: { workerSecret: v.string() },
  returns: v.array(reconcileItem),
  handler: async (ctx, { workerSecret }) => {
    assertWorker(workerSecret);
    const wanted = await ctx.db
      .query("agentInstances")
      .withIndex("by_desired_status", (q) => q.eq("desired", "running"))
      .take(RECONCILE_LIMIT);
    const running = await ctx.db
      .query("agentInstances")
      .withIndex("by_status_heartbeat", (q) => q.eq("status", "running"))
      .take(RECONCILE_LIMIT);
    const byId = new Map<string, (typeof wanted)[number]>();
    for (const r of [...wanted, ...running]) byId.set(r._id, r);
    return [...byId.values()].map((r) => ({
      instanceId: r._id,
      userId: r.userId,
      desired: r.desired as DesiredState,
      status: r.status as InstanceStatus,
      tier: r.tier as FleetTier,
      hostVm: r.hostVm ?? null,
      containerId: r.containerId ?? null,
      heartbeatAt: r.heartbeatAt ?? null,
      lastActiveAt: r.lastActiveAt ?? null,
      wantsAt: r.wantsAt ?? null,
      errorCount: r.errorCount ?? 0,
    }));
  },
});

// ---------------------------------------------------------------------------
// reapIdleInstances (cron, internal) — flip free-tier running containers idle for
// > IDLE_TTL_FREE_MS to desired="stopped"; the controller then `docker stop`s them
// ($0 idle compute). Paid instances stay warm (IDLE_TTL=0, never reaped here).
// Index-scan by_status_heartbeat(status="running"), JS predicate on lastActiveAt
// (bounded take, not a table .filter), paginate via self-reschedule.
// ---------------------------------------------------------------------------
export async function reapIdleInstancesImpl(
  ctx: MutationCtx,
): Promise<{ reaped: number }> {
  const now = Date.now();
  const running = await ctx.db
    .query("agentInstances")
    .withIndex("by_status_heartbeat", (q) => q.eq("status", "running"))
    .take(REAP_BATCH);
  let reaped = 0;
  for (const inst of running) {
    if (inst.tier !== "free") continue;        // paid stays warm
    if (inst.desired !== "running") continue;   // already being torn down
    const idleSince = inst.lastActiveAt ?? inst.startedAt ?? now;
    if (now - idleSince < IDLE_TTL_FREE_MS) continue;
    await ctx.db.patch(inst._id, { desired: "stopped" });
    reaped++;
  }
  if (running.length === REAP_BATCH) {
    await ctx.scheduler.runAfter(0, internal.fleet.reapIdleInstances, {});
  }
  return { reaped };
}

export const reapIdleInstances = internalMutation({
  args: {},
  returns: v.object({ reaped: v.number() }),
  handler: async (ctx) => reapIdleInstancesImpl(ctx),
});
