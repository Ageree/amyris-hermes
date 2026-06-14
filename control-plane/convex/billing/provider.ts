import { StubProvider } from "./stub";

// ---------------------------------------------------------------------------
// BillingProvider adapter (design §6). The app NEVER hard-codes a payment vendor:
// it talks to this interface, and activeProvider() selects the concrete impl from
// BILLING_PROVIDER env. v1 = StubProvider (free fully live; paid behind a
// coming-soon URL). Swapping in Paddle/Stripe later = one new impl + one env flip,
// no changes to app/upgrade or app/tiers. Entitlement writes ALWAYS go through
// billing/grant.applyEntitlement (single writer), so a provider can only ever
// produce a checkout/portal URL or hand a verified webhook to that one writer.
// ---------------------------------------------------------------------------

export interface CheckoutResult {
  ok: boolean;
  checkoutUrl: string | null; // null => not purchasable yet (stub)
  message: string | null;
}

export interface BillingProvider {
  readonly name: string;
  createCheckout(userId: string, tier: "pro" | "max"): Promise<CheckoutResult>;
  portalUrl(userId: string): Promise<string | null>;
  // Verify + parse a provider webhook; the caller routes a verified event to
  // applyEntitlement. The stub never produces real events => { ok: false }.
  handleWebhook(
    payload: unknown,
    headers: Record<string, string>,
  ): Promise<{ ok: boolean }>;
}

export function activeProvider(): BillingProvider {
  // Only the stub exists in v1; the switch is where Paddle/Stripe slot in.
  switch (process.env.BILLING_PROVIDER) {
    case "stub":
    default:
      return new StubProvider();
  }
}
