import { defineTool } from "eve/tools";
import { z } from "zod";
import { rememberUserMemory } from "../lib/supermemory.js";

// Save a durable fact about the user into Supermemory. The API key is supplied by
// SUPERMEMORY_API_KEY and memory is isolated by the Eve tenant session id.
export default defineTool({
  description:
    "Save a durable fact about the user (their profile, a fact, or a preference) so you remember it in future conversations. Use whenever the user shares something worth keeping.",
  inputSchema: z.object({
    kind: z
      .enum(["profile", "fact", "preference"])
      .describe(
        "profile=who they are, fact=something true about them, preference=how they like things",
      ),
    key: z
      .string()
      .min(1)
      .describe("short stable label, e.g. 'home_address' or 'favorite_cuisine'"),
    value: z.string().min(1).describe("the fact to remember"),
  }),
  async execute({ kind, key, value }, ctx) {
    const userId = ctx.session.id;
    const r = await rememberUserMemory({ userId, kind, key, value });
    return r.saved ? { saved: true, kind, key } : { saved: false, error: r.error };
  },
});
