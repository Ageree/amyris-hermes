import { action } from "../_generated/server";
import { v } from "convex/values";
import { requireUser } from "./authGate";
import { activeProvider } from "../billing/provider";

// ---------------------------------------------------------------------------
// app/upgrade:startCheckout — getAuthUserId-gated entry to the payment provider
// (design §2.2). Delegates to activeProvider().createCheckout(userId, tier); v1's
// StubProvider returns a coming-soon URL and no real checkout. It's an action (a
// real provider does an outbound HTTPS call). The userId is the JWT subject —
// never client-supplied — so a client can only ever start ITS OWN checkout.
// ---------------------------------------------------------------------------
export const startCheckout = action({
  args: { tier: v.union(v.literal("pro"), v.literal("max")) },
  returns: v.object({
    ok: v.boolean(),
    checkoutUrl: v.union(v.string(), v.null()),
    message: v.union(v.string(), v.null()),
  }),
  handler: async (ctx, { tier }) => {
    const userId = await requireUser(ctx);
    const result = await activeProvider().createCheckout(userId, tier);
    return {
      ok: result.ok,
      checkoutUrl: result.checkoutUrl,
      message: result.message,
    };
  },
});
