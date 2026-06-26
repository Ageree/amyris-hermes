# Deferred tools — durable-facts fast-follow

`remember.ts` / `recall.ts` were moved out of `tools/` for the Eve-core migration v1.
Conversation memory is handled by the Convex drainer (control-plane/convex/agent.ts),
which injects the last N turns (messages:recentForUser) into each message — parity with
the legacy Hermes worker. No tool needed for short-term recall.

Durable cross-window FACTS (home address, names, tastes) still want these tools + a
`memories` Convex table. Blocker: the tools must key facts by the TENANT userId, but the
generic eve channel authenticates as one service principal ("convex") and exposes no
per-request tenant id in tool ctx. Upgrade path (spec §6):
  1. custom eve channel: drainer POSTs {message, userId}; channel onMessage stores userId
     via defineState (session-scoped) so tools read it from ctx.
  2. control-plane/convex/memories.ts: upsert/list (worker-secret gated, keyed by userId).
  3. re-point remember/recall at memories:* and move them back into tools/.
