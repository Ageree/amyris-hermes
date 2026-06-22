import { v } from "convex/values";

// ---------------------------------------------------------------------------
// Shared WORKER_SECRET gate (invariant A4: worker-facing functions authenticate
// ONLY via this argument gate — never getAuthUserId). Every brain-facing Convex
// function calls assertWorker(args.workerSecret) FIRST. Centralized here so the
// constant-time compare + the env-key contract live in exactly one place; if the
// gate ever changes (per-user secrets, A8 hardening) it changes once.
// ---------------------------------------------------------------------------

// Constant-time string compare — never short-circuit on a mismatched byte, so an
// attacker can't time the comparison to recover the secret byte-by-byte. The
// length check leaks only length, which is fixed for our secrets.
function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/**
 * Reject unless `provided` matches process.env.WORKER_SECRET (constant-time).
 * Throws "unauthorized worker" otherwise — and ALSO when no secret is configured,
 * so a misconfigured deployment fails closed rather than accepting any caller.
 */
export function assertWorker(provided: string): void {
  const expected = process.env.WORKER_SECRET ?? "";
  if (!expected || !safeEqual(provided, expected)) {
    throw new Error("unauthorized worker");
  }
}

/**
 * Gate for the chat-sites `publish` action. DELIBERATELY a SEPARATE, narrowly
 * scoped secret (not WORKER_SECRET): `publish.py` runs inside the agent's
 * `terminal` tool, which processes untrusted inbound text, so a prompt-injected
 * agent could read whatever secret reaches that env. Scoping this to "can publish
 * sites" bounds the blast radius — it can never claim/complete/read the queue the
 * way WORKER_SECRET would. Fails closed when unconfigured.
 */
export function assertSitesPublisher(provided: string): void {
  const expected = process.env.SITES_PUBLISH_SECRET ?? "";
  if (!expected || !safeEqual(provided, expected)) {
    throw new Error("unauthorized publisher");
  }
}

// ---------------------------------------------------------------------------
// Reusable literal-union validators — ONE source so function arg/return
// validators never drift from each other. (schema.ts intentionally keeps its own
// local copies to stay byte-for-byte the design's verbatim target; these mirror
// those exact literals so the functions and the schema agree.)
// ---------------------------------------------------------------------------
export const channelValidator = v.union(
  v.literal("imessage"),
  v.literal("telegram"),
);

export const tierValidator = v.union(
  v.literal("free"),
  v.literal("pro"),
  v.literal("max"),
);
