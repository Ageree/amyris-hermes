import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

// Durable inbound queue. Sendblue posts here via the HTTP endpoint (always-on,
// no tunnel). The "brain" (Hermes + real browser, running on the Mac or a cloud
// VM) polls `claimNext`, processes, then calls `complete`/`fail`. Because the
// queue is durable, messages are NEVER lost when the brain is offline — they sit
// as "queued" and get picked up when it comes back.
export default defineSchema({
  messages: defineTable({
    handle: v.string(), // Sendblue message_handle — idempotency key
    userNumber: v.string(), // sender (end-user) E.164 number
    text: v.string(),
    mediaUrl: v.optional(v.string()),
    status: v.union(
      v.literal("queued"),
      v.literal("processing"),
      v.literal("done"),
      v.literal("error"),
    ),
    reply: v.optional(v.string()),
    receivedAt: v.number(),
    claimedAt: v.optional(v.number()),
    completedAt: v.optional(v.number()),
    error: v.optional(v.string()),
  })
    .index("by_handle", ["handle"])
    .index("by_status", ["status", "receivedAt"]),

  // Pending "connect intents": when the agent sends a connect-link for a task, it
  // records the original task + the toolkits it needs. The worker polls Composio
  // status; when all required toolkits are ACTIVE it enqueues a synthetic resume
  // message (resolveIntent) so the task completes itself — no 2nd user message.
  connectIntents: defineTable({
    userNumber: v.string(),
    taskText: v.string(),
    requiredToolkits: v.array(v.string()),
    connectedToolkits: v.array(v.string()),
    status: v.union(v.literal("pending"), v.literal("resumed"), v.literal("expired")),
    createdAt: v.number(),
    resumedAt: v.optional(v.number()),
  }).index("by_status", ["status", "createdAt"]),
});
