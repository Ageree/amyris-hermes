import type { BillingProvider, CheckoutResult } from "./provider";

// ---------------------------------------------------------------------------
// StubProvider (design §6) — v1 billing. The FREE tier is fully live (granted by
// app/tiers:chooseTier via applyEntitlement); paid tiers are not purchasable yet,
// so createCheckout returns a coming-soon URL with no checkout and handleWebhook
// always returns { ok: false } (the stub never emits real events). Replacing this
// with a real provider is one new file + a BILLING_PROVIDER env flip.
// ---------------------------------------------------------------------------

export const COMING_SOON = "/dashboard?upgrade=coming-soon";

export class StubProvider implements BillingProvider {
  readonly name = "stub";

  async createCheckout(_userId: string, _tier: "pro" | "max"): Promise<CheckoutResult> {
    return {
      ok: false,
      checkoutUrl: COMING_SOON,
      message: "paid plans are launching soon — you're on free for now.",
    };
  }

  async portalUrl(_userId: string): Promise<string | null> {
    return null;
  }

  async handleWebhook(): Promise<{ ok: boolean }> {
    return { ok: false };
  }
}
