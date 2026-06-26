import { defineTool } from "eve/tools";
import { z } from "zod";
import { convexCall } from "../lib/convex.js";

// Save a durable fact about the user into the Convex `memories` table (spec §6).
export default defineTool({
  description:
    "Save a durable fact about the user (their profile, a fact, or a preference) so you remember it in future conversations. Use whenever the user shares something worth keeping.",
  inputSchema: z.object({
    kind: z
      .enum(["profile", "fact", "preference"])
      .describe("profile=who they are, fact=something true about them, preference=how they like things"),
    key: z
      .string()
      .min(1)
      .describe("short stable label, e.g. 'home_address' or 'favorite_cuisine'"),
    value: z.string().min(1).describe("the fact to remember"),
  }),
  async execute({ kind, key, value }, ctx) {
    // The durable session is keyed by the tenant userId (spec §4); memory is isolated
    // strictly by userId (invariant A1).
    const userId = ctx.session.id;
    // ponytail: targets a Convex mutation that does not exist yet (ceiling: every save
    // errors until it's created) — we return the real round-trip result, never a faked
    // success. Upgrade path: add the mutation below.
    // TODO(core): create Convex memories.upsert mutation ({workerSecret, userId, kind, key, value})
    const r = await convexCall("mutation", "memories:upsert", {
      userId,
      kind,
      key,
      value,
    });
    return r.ok ? { saved: true, kind, key } : { saved: false, error: r.error };
  },
});
