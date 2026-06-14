import { getAuthUserId } from "@convex-dev/auth/server";
import type { Id } from "../_generated/dataModel";

// ---------------------------------------------------------------------------
// requireUser — THE user-facing auth gate (invariant A4: app/* functions
// authenticate ONLY via the JWT subject, NEVER a client-supplied userId and
// NEVER the WORKER_SECRET). Every app/* query/mutation/action calls this FIRST
// and scopes all reads/writes to the returned Id<"users">. getAuthUserId reads
// the verified identity from the request's JWT, so a client can never act as
// another tenant. Throws (fail-closed) when unauthenticated. Lives UNDER app/ so
// the whole user-facing surface is provably gated by one helper.
// ---------------------------------------------------------------------------
export async function requireUser(ctx: { auth: any }): Promise<Id<"users">> {
  const userId = await getAuthUserId(ctx as any);
  if (userId === null) {
    throw new Error("unauthenticated");
  }
  return userId;
}
