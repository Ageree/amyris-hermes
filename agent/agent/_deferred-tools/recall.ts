import { defineTool } from "eve/tools";
import { z } from "zod";
import { convexCall } from "../lib/convex.js";
import { recallUserMemory } from "../lib/supermemory.js";

// Recall saved facts + recent conversation context for the user (spec §6). Mirror of
// `remember`: facts come from the `memories` table, recent dialogue from messages.
export default defineTool({
  description:
    "Recall what you know about the user — saved facts/preferences and recent conversation context. Call this when you need personal context you don't already have in view.",
  inputSchema: z.object({
    query: z.string().optional().describe("optional topic to narrow the recall"),
    kind: z
      .string()
      .optional()
      .describe("optional filter: profile | fact | preference"),
  }),
  async execute({ query, kind }, ctx) {
    const userId = ctx.session.id; // tenant key (invariant A1)
    const facts = await recallUserMemory({ userId, query, kind, limit: 10 });
    // Recent dialogue context — messages.recentForUser already exists (control-plane).
    const recent = await convexCall("query", "messages:recentForUser", {
      userId,
      limit: 10,
    });
    return {
      facts: facts.facts,
      recent: recent.ok ? recent.value : [],
      ...("error" in facts ? { factsError: facts.error } : {}),
      ...(recent.ok ? {} : { recentError: recent.error }),
    };
  },
});
