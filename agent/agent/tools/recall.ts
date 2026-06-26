import { defineTool } from "eve/tools";
import { z } from "zod";
import { convexCall } from "../lib/convex.js";

// Recall saved facts + recent conversation context for the user (spec §6). Mirror of
// `remember`: facts come from the `memories` table, recent dialogue from messages.
export default defineTool({
  description:
    "Recall what you know about the user — saved facts/preferences and recent conversation context. Call this when you need personal context you don't already have in view.",
  inputSchema: z.object({
    query: z.string().optional().describe("optional topic to narrow the recall"),
    kind: z.string().optional().describe("optional filter: profile | fact | preference"),
  }),
  async execute({ query, kind }, ctx) {
    const userId = ctx.session.id; // tenant key (invariant A1)
    // Facts from the memories table.
    // ponytail: memories.list does not exist yet (ceiling: facts come back empty with
    // an error string until it's created); recentForUser below is real and already wired.
    // TODO(core): create Convex memories.list query ({workerSecret, userId, query?, kind?})
    const facts = await convexCall("query", "memories:list", { userId, query, kind });
    // Recent dialogue context — messages.recentForUser already exists (control-plane).
    const recent = await convexCall("query", "messages:recentForUser", {
      userId,
      limit: 10,
    });
    return {
      facts: facts.ok ? facts.value : [],
      recent: recent.ok ? recent.value : [],
      ...(facts.ok ? {} : { factsError: facts.error }),
      ...(recent.ok ? {} : { recentError: recent.error }),
    };
  },
});
