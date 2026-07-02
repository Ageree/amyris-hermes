import {
  internalMutation,
  internalQuery,
  mutation,
  query,
  type MutationCtx,
  type QueryCtx,
} from "./_generated/server";
import { v } from "convex/values";
import { internal } from "./_generated/api";
import type { Doc, Id } from "./_generated/dataModel";
import { assertWorker, channelValidator } from "./lib/auth";

const internalAny = internal as any;

const TASK_TTL_MS = 24 * 60 * 60_000;
const RUNNING_TASK_TIMEOUT_MS = 2 * 60 * 60_000;
const TASK_REAP_BATCH = 500;
const MAX_REQUEST_CHARS = 2000;
const MAX_RESULT_CHARS = 4000;
const MAX_FAILURE_REASON_CHARS = 300;

const crewLinkStatus = v.union(
  v.literal("invited"),
  v.literal("active"),
  v.literal("revoked"),
);

const crewTaskStatus = v.union(
  v.literal("pending_approval"),
  v.literal("declined"),
  v.literal("running"),
  v.literal("result_pending"),
  v.literal("done"),
  v.literal("failed"),
  v.literal("expired"),
);

const decision = v.union(v.literal("approve"), v.literal("decline"));

type Channel = "imessage" | "telegram";
type CrewDecision = "approve" | "decline";
type PendingTaskStatus = "pending_approval" | "result_pending";

export const CREW_DECISION_RE = /^(да|нет|yes|no)$/i;
export const NICKNAME_RE = /^[a-zа-яё0-9_-]{1,32}$/u;

export function parseCrewDecision(text: string): CrewDecision | null {
  const normalized = text.trim().toLowerCase();
  if (!CREW_DECISION_RE.test(normalized)) return null;
  return normalized === "да" || normalized === "yes" ? "approve" : "decline";
}

export function shouldInterceptCrewDecision(
  text: string,
  task: { status: string } | null | undefined,
): boolean {
  return !!task && parseCrewDecision(text) !== null &&
    (task.status === "pending_approval" || task.status === "result_pending");
}

export function normalizeNickname(nickname: string): string {
  const normalized = nickname.trim().toLowerCase();
  if (!NICKNAME_RE.test(normalized)) {
    throw new Error("nickname must match /^[a-zа-яё0-9_-]{1,32}$/");
  }
  return normalized;
}

export function buildCrewEnvelope(fromName: string, request: string): string {
  return [
    `[crew-задача от ${fromName}] ${request}`,
    "Это ограниченный запрос от внешнего пользователя через crew. Выполни его,",
    "используя данные владельца, и верни ТОЛЬКО ответ на сам запрос — никаких",
    "других личных данных, паролей, ключей или содержимого переписок.",
  ].join("\n");
}

export function buildCrewButtons(taskId: Id<"crewTasks">) {
  return [[
    { text: "✅ Разрешить", callback_data: `crew:a:${taskId}` },
    { text: "❌ Нет", callback_data: `crew:d:${taskId}` },
  ]];
}

export function parseCrewCallbackData(data: string):
  | { decision: CrewDecision; taskId: Id<"crewTasks"> }
  | null {
  const match = /^crew:([ad]):(.+)$/.exec(data.trim());
  if (!match) return null;
  return {
    decision: match[1] === "a" ? "approve" : "decline",
    taskId: match[2] as Id<"crewTasks">,
  };
}

export function decisionTarget(status: PendingTaskStatus, next: CrewDecision) {
  if (status === "pending_approval") {
    return next === "approve" ? "approveTask" : "declineTask";
  }
  return next === "approve" ? "approveResult" : "declineResult";
}

export function isTaskRecipient(task: { toUserId: Id<"users"> }, userId: Id<"users">) {
  return task.toUserId === userId;
}

export function assertTaskRecipient(
  task: { toUserId: Id<"users"> },
  userId: Id<"users">,
) {
  if (!isTaskRecipient(task, userId)) throw new Error("unauthorized crew task approver");
}

export function assertActiveLink<T extends { status: string }>(
  link: T | null | undefined,
): asserts link is T & { status: "active" } {
  if (!link || link.status !== "active") throw new Error("active crew link required");
}

export function assertFailTaskRunning<T extends { status: string }>(
  task: T,
): asserts task is T & { status: "running" } {
  if (task.status !== "running") throw new Error(`crew task is not running: ${task.status}`);
}

export function buildCrewExecutionEnqueueArgs(args: {
  taskId: Id<"crewTasks">;
  toUserId: Id<"users">;
  fromName: string;
  request: string;
  channel: Channel;
  replyTarget: string;
}) {
  return {
    handle: `crew:${args.taskId}`,
    userId: args.toUserId,
    channel: args.channel,
    replyTarget: args.replyTarget,
    userNumber: args.replyTarget,
    text: buildCrewEnvelope(args.fromName, args.request),
    crewTaskId: args.taskId,
  };
}

export async function scheduleCrewNotify(
  ctx: Pick<MutationCtx, "scheduler">,
  args: {
    userId: Id<"users">;
    text: string;
    tgButtons?: ReturnType<typeof buildCrewButtons>;
  },
) {
  await ctx.scheduler.runAfter(0, internalAny.lib.notify.notifyUser, args);
}

function displayName(user: Doc<"users"> | null): string {
  return (
    user?.displayName?.trim() ||
    user?.name?.trim() ||
    user?.phone?.trim() ||
    user?.email?.trim() ||
    "пользователь"
  );
}

function failureReason(reason: string): string {
  const text = reason.trim().replace(/\s+/g, " ");
  return (text || "ошибка выполнения").slice(0, MAX_FAILURE_REASON_CHARS);
}

function buildCrewFailureNotice(nickname: string, reason: string): string {
  return `агент ${nickname} — задача не выполнена: ${reason}`;
}

function nicknameBase(name: string): string {
  const base = name
    .trim()
    .toLowerCase()
    .replace(/[^a-zа-яё0-9_-]+/gu, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32);
  return base || "user";
}

async function uniqueReverseNickname(
  ctx: MutationCtx,
  ownerUserId: Id<"users">,
  peerName: string,
): Promise<string> {
  const base = nicknameBase(peerName);
  for (let i = 1; i <= 99; i++) {
    const suffix = i === 1 ? "" : `-${i}`;
    const maxBase = 32 - suffix.length;
    const candidate = `${base.slice(0, maxBase)}${suffix}`;
    const existing = await ctx.db
      .query("crewLinks")
      .withIndex("by_owner_nick", (q) =>
        q.eq("ownerUserId", ownerUserId).eq("nickname", candidate),
      )
      .first();
    if (!existing || existing.status === "revoked") return candidate;
  }
  throw new Error("cannot allocate reverse crew nickname");
}

async function resolveCrewUser(ctx: MutationCtx, contact: string): Promise<Id<"users">> {
  const normalized = contact.trim();
  const byPhone = await ctx.db
    .query("users")
    .withIndex("phone", (q) => q.eq("phone", normalized))
    .first();
  if (byPhone) return byPhone._id;

  const binding = await ctx.db
    .query("channelBindings")
    .withIndex("by_address", (q) =>
      q.eq("channel", "imessage").eq("address", normalized),
    )
    .first();
  if (binding?.verified) return binding.userId;
  throw new Error("не пользователь dhizume");
}

async function activeLinkByNickname(
  ctx: QueryCtx | MutationCtx,
  ownerUserId: Id<"users">,
  nickname: string,
) {
  const row = await ctx.db
    .query("crewLinks")
    .withIndex("by_owner_nick", (q) =>
      q.eq("ownerUserId", ownerUserId).eq("nickname", nickname),
    )
    .first();
  return row?.status === "active" ? row : null;
}

async function nicknameForPeer(
  ctx: QueryCtx | MutationCtx,
  ownerUserId: Id<"users">,
  peerUserId: Id<"users">,
): Promise<string> {
  const rows = await ctx.db
    .query("crewLinks")
    .withIndex("by_owner_status", (q) =>
      q.eq("ownerUserId", ownerUserId).eq("status", "active"),
    )
    .take(200);
  return rows.find((r) => r.peerUserId === peerUserId)?.nickname ?? "crew";
}

async function freshestBinding(
  ctx: QueryCtx | MutationCtx,
  userId: Id<"users">,
): Promise<{ channel: Channel; address: string } | null> {
  const rows = await ctx.db
    .query("channelBindings")
    .withIndex("by_user", (q) => q.eq("userId", userId))
    .collect();
  const verified = rows.filter((r) => r.verified);
  if (!verified.length) return null;
  verified.sort((a, b) => (b.lastInboundAt ?? b.createdAt) - (a.lastInboundAt ?? a.createdAt));
  return { channel: verified[0].channel, address: verified[0].address };
}

async function verifiedBindingByAddress(
  ctx: MutationCtx,
  userId: Id<"users">,
  channel: Channel,
  address: string,
) {
  const binding = await ctx.db
    .query("channelBindings")
    .withIndex("by_address", (q) => q.eq("channel", channel).eq("address", address))
    .first();
  return !!binding && binding.verified && binding.userId === userId;
}

async function executionTarget(
  ctx: MutationCtx,
  userId: Id<"users">,
  channel?: Channel,
  replyTarget?: string,
): Promise<{ channel: Channel; replyTarget: string }> {
  if (channel && replyTarget && await verifiedBindingByAddress(ctx, userId, channel, replyTarget)) {
    return { channel, replyTarget };
  }
  const binding = await freshestBinding(ctx, userId);
  if (!binding) throw new Error("no verified channel binding for crew task recipient");
  return { channel: binding.channel, replyTarget: binding.address };
}

async function latestPendingTask(
  ctx: QueryCtx,
  userId: Id<"users">,
): Promise<{ taskId: Id<"crewTasks">; status: PendingTaskStatus; createdAt: number } | null> {
  const rows = await Promise.all(
    (["pending_approval", "result_pending"] as const).map(async (status) => {
      const row = await ctx.db
        .query("crewTasks")
        .withIndex("by_to_status", (q) =>
          q.eq("toUserId", userId).eq("status", status),
        )
        .order("desc")
        .first();
      return row ? { taskId: row._id, status, createdAt: row.createdAt } : null;
    }),
  );
  const present = rows.filter((r): r is NonNullable<typeof r> => r !== null);
  present.sort((a, b) => b.createdAt - a.createdAt);
  return present[0] ?? null;
}

async function latestInvite(
  ctx: QueryCtx,
  userId: Id<"users">,
): Promise<{ linkId: Id<"crewLinks">; createdAt: number } | null> {
  const rows = await ctx.db
    .query("crewLinks")
    .withIndex("by_peer_status", (q) =>
      q.eq("peerUserId", userId).eq("status", "invited"),
    )
    .take(200);
  rows.sort((a, b) => b.createdAt - a.createdAt);
  const newest = rows[0];
  return newest ? { linkId: newest._id, createdAt: newest.createdAt } : null;
}

async function acceptInviteImpl(ctx: MutationCtx, linkId: Id<"crewLinks">, userId: Id<"users">) {
  const link = await ctx.db.get(linkId);
  if (!link) throw new Error("crew invite not found");
  if (link.peerUserId !== userId) throw new Error("unauthorized crew invite recipient");
  if (link.status !== "invited") throw new Error(`crew invite is not pending: ${link.status}`);

  const now = Date.now();
  await ctx.db.patch(link._id, { status: "active", acceptedAt: now });

  const owner = await ctx.db.get(link.ownerUserId);
  const reverseNick = await uniqueReverseNickname(ctx, link.peerUserId, displayName(owner));
  const reverse = await ctx.db
    .query("crewLinks")
    .withIndex("by_owner_nick", (q) =>
      q.eq("ownerUserId", link.peerUserId).eq("nickname", reverseNick),
    )
    .first();
  const reverseFields = {
    ownerUserId: link.peerUserId,
    peerUserId: link.ownerUserId,
    nickname: reverseNick,
    status: "active" as const,
    createdAt: now,
    acceptedAt: now,
  };
  if (reverse) await ctx.db.patch(reverse._id, reverseFields);
  else await ctx.db.insert("crewLinks", reverseFields);

  const peer = await ctx.db.get(link.peerUserId);
  await scheduleCrewNotify(ctx, {
    userId: link.ownerUserId,
    text: `${displayName(peer)} теперь в твоём crew`,
  });
  await scheduleCrewNotify(ctx, {
    userId: link.peerUserId,
    text: `${displayName(owner)} теперь в твоём crew`,
  });
  return { status: "active" as const };
}

async function declineInviteImpl(ctx: MutationCtx, linkId: Id<"crewLinks">, userId: Id<"users">) {
  const link = await ctx.db.get(linkId);
  if (!link) throw new Error("crew invite not found");
  if (link.peerUserId !== userId) throw new Error("unauthorized crew invite recipient");
  if (link.status !== "invited") throw new Error(`crew invite is not pending: ${link.status}`);
  await ctx.db.patch(link._id, { status: "revoked" });
  const peer = await ctx.db.get(link.peerUserId);
  await scheduleCrewNotify(ctx, {
    userId: link.ownerUserId,
    text: `${displayName(peer)} отклонила crew`,
  });
  return { status: "revoked" as const };
}

async function approveTaskImpl(
  ctx: MutationCtx,
  args: {
    taskId: Id<"crewTasks">;
    userId: Id<"users">;
    channel?: Channel;
    replyTarget?: string;
  },
) {
  const task = await ctx.db.get(args.taskId);
  if (!task) throw new Error("crew task not found");
  assertTaskRecipient(task, args.userId);
  if (task.status === "running" && task.messageId) {
    return { status: "running" as const, messageId: task.messageId };
  }
  if (task.status !== "pending_approval") {
    throw new Error(`crew task is not pending approval: ${task.status}`);
  }

  const [fromUser, target] = await Promise.all([
    ctx.db.get(task.fromUserId),
    executionTarget(ctx, task.toUserId, args.channel, args.replyTarget),
  ]);
  const enqueueArgs = buildCrewExecutionEnqueueArgs({
    taskId: task._id,
    toUserId: task.toUserId,
    fromName: displayName(fromUser),
    request: task.request,
    channel: target.channel,
    replyTarget: target.replyTarget,
  });
  const messageId: Id<"messages"> = await ctx.runMutation(
    internal.messages.enqueue,
    enqueueArgs,
  );
  const now = Date.now();
  await ctx.db.patch(task._id, { status: "running", approvedAt: now, messageId });
  try {
    await ctx.runMutation(internal.fleet.requestInstanceInternal, {
      userId: task.toUserId,
      channel: target.channel,
    });
  } catch {
    // Durable enqueue already succeeded; a later inbound or worker poll can recover.
  }
  return { status: "running" as const, messageId };
}

async function declineTaskImpl(ctx: MutationCtx, taskId: Id<"crewTasks">, userId: Id<"users">) {
  const task = await ctx.db.get(taskId);
  if (!task) throw new Error("crew task not found");
  assertTaskRecipient(task, userId);
  if (task.status !== "pending_approval") {
    throw new Error(`crew task is not pending approval: ${task.status}`);
  }
  const now = Date.now();
  await ctx.db.patch(task._id, { status: "declined", completedAt: now });
  const nickname = await nicknameForPeer(ctx, task.fromUserId, task.toUserId);
  await scheduleCrewNotify(ctx, {
    userId: task.fromUserId,
    text: `${nickname} отклонила запрос`,
  });
  return { status: "declined" as const };
}

async function approveResultImpl(ctx: MutationCtx, taskId: Id<"crewTasks">, userId: Id<"users">) {
  const task = await ctx.db.get(taskId);
  if (!task) throw new Error("crew task not found");
  assertTaskRecipient(task, userId);
  if (task.status !== "result_pending" || !task.resultText) {
    throw new Error(`crew task result is not pending: ${task.status}`);
  }
  const nickname = await nicknameForPeer(ctx, task.fromUserId, task.toUserId);
  await ctx.db.patch(task._id, { status: "done", completedAt: Date.now() });
  await scheduleCrewNotify(ctx, {
    userId: task.fromUserId,
    text: `агент ${nickname}: ${task.resultText}`,
  });
  return { status: "done" as const };
}

async function declineResultImpl(ctx: MutationCtx, taskId: Id<"crewTasks">, userId: Id<"users">) {
  const task = await ctx.db.get(taskId);
  if (!task) throw new Error("crew task not found");
  assertTaskRecipient(task, userId);
  if (task.status !== "result_pending") {
    throw new Error(`crew task result is not pending: ${task.status}`);
  }
  const nickname = await nicknameForPeer(ctx, task.fromUserId, task.toUserId);
  await ctx.db.patch(task._id, { status: "failed", completedAt: Date.now() });
  await scheduleCrewNotify(ctx, {
    userId: task.fromUserId,
    text: `${nickname} отклонила ответ`,
  });
  return { status: "failed" as const };
}

async function failRunningTaskImpl(
  ctx: MutationCtx,
  task: Doc<"crewTasks">,
  reason: string,
  now: number,
) {
  assertFailTaskRunning(task);
  const text = failureReason(reason);
  await ctx.db.patch(task._id, { status: "failed", completedAt: now });
  const nickname = await nicknameForPeer(ctx, task.fromUserId, task.toUserId);
  await scheduleCrewNotify(ctx, {
    userId: task.fromUserId,
    text: buildCrewFailureNotice(nickname, text),
  });
  return { status: "failed" as const };
}

export const createInvite = mutation({
  args: {
    workerSecret: v.string(),
    fromUserId: v.id("users"),
    contact: v.string(),
    nickname: v.string(),
  },
  returns: v.object({ linkId: v.id("crewLinks"), toUserId: v.id("users") }),
  handler: async (ctx, { workerSecret, fromUserId, contact, nickname }) => {
    assertWorker(workerSecret);
    const nick = normalizeNickname(nickname);
    const toUserId = await resolveCrewUser(ctx, contact);
    if (toUserId === fromUserId) throw new Error("нельзя добавить себя в crew");

    const existing = await ctx.db
      .query("crewLinks")
      .withIndex("by_owner_nick", (q) =>
        q.eq("ownerUserId", fromUserId).eq("nickname", nick),
      )
      .first();
    if (existing && existing.status !== "revoked") {
      throw new Error("crew nickname already exists");
    }

    const now = Date.now();
    const fields = {
      ownerUserId: fromUserId,
      peerUserId: toUserId,
      nickname: nick,
      status: "invited" as const,
      createdAt: now,
      acceptedAt: undefined,
    };
    const linkId = existing
      ? (await ctx.db.patch(existing._id, fields), existing._id)
      : await ctx.db.insert("crewLinks", fields);

    const fromUser = await ctx.db.get(fromUserId);
    await scheduleCrewNotify(ctx, {
      userId: toUserId,
      text: `${displayName(fromUser)} хочет связать ваших агентов. Ответь ДА или НЕТ`,
    });
    return { linkId, toUserId };
  },
});

export const acceptInvite = internalMutation({
  args: { linkId: v.id("crewLinks"), userId: v.id("users") },
  returns: v.object({ status: crewLinkStatus }),
  handler: async (ctx, { linkId, userId }) => acceptInviteImpl(ctx, linkId, userId),
});

export const declineInvite = internalMutation({
  args: { linkId: v.id("crewLinks"), userId: v.id("users") },
  returns: v.object({ status: crewLinkStatus }),
  handler: async (ctx, { linkId, userId }) => declineInviteImpl(ctx, linkId, userId),
});

export const decideInvite = internalMutation({
  args: { linkId: v.id("crewLinks"), userId: v.id("users"), decision },
  returns: v.object({ status: crewLinkStatus }),
  handler: async (ctx, { linkId, userId, decision: next }) => {
    return next === "approve"
      ? await acceptInviteImpl(ctx, linkId, userId)
      : await declineInviteImpl(ctx, linkId, userId);
  },
});

export const createTask = mutation({
  args: {
    workerSecret: v.string(),
    fromUserId: v.id("users"),
    nickname: v.string(),
    request: v.string(),
  },
  returns: v.object({ taskId: v.id("crewTasks"), status: crewTaskStatus }),
  handler: async (ctx, { workerSecret, fromUserId, nickname, request }) => {
    assertWorker(workerSecret);
    const nick = normalizeNickname(nickname);
    const text = request.trim();
    if (!text || text.length > MAX_REQUEST_CHARS) {
      throw new Error("crew request must be 1..2000 chars");
    }
    const link = await activeLinkByNickname(ctx, fromUserId, nick);
    assertActiveLink(link);

    const now = Date.now();
    const taskId = await ctx.db.insert("crewTasks", {
      fromUserId,
      toUserId: link.peerUserId,
      request: text,
      status: "pending_approval",
      createdAt: now,
      expiresAt: now + TASK_TTL_MS,
    });
    const fromUser = await ctx.db.get(fromUserId);
    await scheduleCrewNotify(ctx, {
      userId: link.peerUserId,
      text: `Агент ${displayName(fromUser)} просит: „${text}“. Разрешить? ДА/НЕТ`,
      tgButtons: buildCrewButtons(taskId),
    });
    return { taskId, status: "pending_approval" as const };
  },
});

export const approveTask = internalMutation({
  args: {
    taskId: v.id("crewTasks"),
    userId: v.id("users"),
    channel: v.optional(channelValidator),
    replyTarget: v.optional(v.string()),
  },
  returns: v.object({ status: crewTaskStatus, messageId: v.id("messages") }),
  handler: async (ctx, args) => approveTaskImpl(ctx, args),
});

export const declineTask = internalMutation({
  args: { taskId: v.id("crewTasks"), userId: v.id("users") },
  returns: v.object({ status: crewTaskStatus }),
  handler: async (ctx, { taskId, userId }) => declineTaskImpl(ctx, taskId, userId),
});

export const submitResult = mutation({
  args: {
    workerSecret: v.string(),
    taskId: v.id("crewTasks"),
    resultText: v.string(),
  },
  returns: v.object({ status: crewTaskStatus }),
  handler: async (ctx, { workerSecret, taskId, resultText }) => {
    assertWorker(workerSecret);
    const text = resultText.trim();
    if (!text || text.length > MAX_RESULT_CHARS) {
      throw new Error("crew result must be 1..4000 chars");
    }
    const task = await ctx.db.get(taskId);
    if (!task) throw new Error("crew task not found");
    if (task.status !== "running") throw new Error(`crew task is not running: ${task.status}`);

    await ctx.db.patch(task._id, { status: "result_pending", resultText: text, completedAt: Date.now() });
    const fromUser = await ctx.db.get(task.fromUserId);
    await scheduleCrewNotify(ctx, {
      userId: task.toUserId,
      text: `Отправить ${displayName(fromUser)}: „${text}“? ДА/НЕТ`,
      tgButtons: buildCrewButtons(task._id),
    });
    return { status: "result_pending" as const };
  },
});

export const failTask = mutation({
  args: {
    workerSecret: v.string(),
    taskId: v.id("crewTasks"),
    reason: v.string(),
  },
  returns: v.object({ status: crewTaskStatus }),
  handler: async (ctx, { workerSecret, taskId, reason }) => {
    assertWorker(workerSecret);
    const task = await ctx.db.get(taskId);
    if (!task) throw new Error("crew task not found");
    return await failRunningTaskImpl(ctx, task, reason, Date.now());
  },
});

export const approveResult = internalMutation({
  args: { taskId: v.id("crewTasks"), userId: v.id("users") },
  returns: v.object({ status: crewTaskStatus }),
  handler: async (ctx, { taskId, userId }) => approveResultImpl(ctx, taskId, userId),
});

export const declineResult = internalMutation({
  args: { taskId: v.id("crewTasks"), userId: v.id("users") },
  returns: v.object({ status: crewTaskStatus }),
  handler: async (ctx, { taskId, userId }) => declineResultImpl(ctx, taskId, userId),
});

export const decideTask = internalMutation({
  args: {
    taskId: v.id("crewTasks"),
    userId: v.id("users"),
    decision,
    channel: v.optional(channelValidator),
    replyTarget: v.optional(v.string()),
  },
  returns: v.object({ status: crewTaskStatus }),
  handler: async (ctx, { taskId, userId, decision: next, channel, replyTarget }) => {
    const task = await ctx.db.get(taskId);
    if (!task) throw new Error("crew task not found");
    assertTaskRecipient(task, userId);
    if (task.status === "pending_approval") {
      if (next === "approve") {
        const result = await approveTaskImpl(ctx, { taskId, userId, channel, replyTarget });
        return { status: result.status };
      }
      return await declineTaskImpl(ctx, taskId, userId);
    }
    if (task.status === "result_pending") {
      return next === "approve"
        ? await approveResultImpl(ctx, taskId, userId)
        : await declineResultImpl(ctx, taskId, userId);
    }
    throw new Error(`crew task is not waiting for decision: ${task.status}`);
  },
});

export const latestPendingForUser = internalQuery({
  args: { userId: v.id("users") },
  returns: v.union(
    v.object({
      taskId: v.id("crewTasks"),
      status: v.union(v.literal("pending_approval"), v.literal("result_pending")),
      createdAt: v.number(),
    }),
    v.null(),
  ),
  handler: async (ctx, { userId }) => latestPendingTask(ctx, userId),
});

export const latestInviteForUser = internalQuery({
  args: { userId: v.id("users") },
  returns: v.union(
    v.object({
      linkId: v.id("crewLinks"),
      createdAt: v.number(),
    }),
    v.null(),
  ),
  handler: async (ctx, { userId }) => latestInvite(ctx, userId),
});

export const listLinks = query({
  args: { workerSecret: v.string(), userId: v.id("users") },
  returns: v.array(
    v.object({
      peerUserId: v.id("users"),
      nickname: v.string(),
      status: crewLinkStatus,
    }),
  ),
  handler: async (ctx, { workerSecret, userId }) => {
    assertWorker(workerSecret);
    const rows = await ctx.db
      .query("crewLinks")
      .withIndex("by_owner_status", (q) =>
        q.eq("ownerUserId", userId).eq("status", "active"),
      )
      .collect();
    return rows.map((r) => ({
      peerUserId: r.peerUserId,
      nickname: r.nickname,
      status: r.status,
    }));
  },
});

export const expirePending = internalMutation({
  args: {},
  returns: v.object({ expired: v.number() }),
  handler: async (ctx) => {
    const now = Date.now();
    let expired = 0;
    for (const status of ["pending_approval", "result_pending"] as const) {
      const rows = await ctx.db
        .query("crewTasks")
        .withIndex("by_status_expiry", (q) =>
          q.eq("status", status).lt("expiresAt", now),
        )
        .take(TASK_REAP_BATCH);
      for (const task of rows) {
        await ctx.db.patch(task._id, { status: "expired", completedAt: now });
        await scheduleCrewNotify(ctx, {
          userId: task.fromUserId,
          text: "истёк без ответа",
        });
        expired++;
      }
      if (rows.length === TASK_REAP_BATCH) {
        await ctx.scheduler.runAfter(0, internalAny.crew.expirePending, {});
      }
    }
    const running = await ctx.db
      .query("crewTasks")
      .withIndex("by_status_expiry", (q) => q.eq("status", "running"))
      .order("asc")
      .take(TASK_REAP_BATCH);
    let failedRunning = 0;
    for (const task of running) {
      const startedAt = task.approvedAt ?? task.createdAt;
      if (now - startedAt < RUNNING_TASK_TIMEOUT_MS) break;
      await failRunningTaskImpl(ctx, task, "истекло время выполнения", now);
      failedRunning++;
      expired++;
    }
    if (running.length === TASK_REAP_BATCH && failedRunning === running.length) {
      await ctx.scheduler.runAfter(0, internalAny.crew.expirePending, {});
    }
    return { expired };
  },
});
