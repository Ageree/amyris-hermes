import { test, expect, type Page, type BrowserContext } from "@playwright/test";
import {
  uniqueEmail,
  signUpViaPassword,
  convexClient,
  readPairToken,
  redeemTelegram,
  uniqueTelegramAddress,
} from "./helpers";

// Tenant isolation: two independent users each bind their own telegram address.
// User A's dashboard must show A's channel and never leak B's. Each user mints
// their OWN pairing token from their OWN /connect session, so the bind is truly
// scoped per-account. Skipped without WORKER_SECRET (the bind wrapper is gated).

test.describe("tenant isolation", () => {
  test.skip(
    !process.env.WORKER_SECRET,
    "requires WORKER_SECRET to call the testing:* convex wrappers",
  );

  // The dashboard masks addresses to the last 4 chars ("••• <last4>"), so we
  // assert on that tail. Our addresses are built with distinct tails per user.
  function tail4(address: string): string {
    return address.slice(-4);
  }

  // Run the full sign-up → connect → bind flow for one user in its own context,
  // returning the address (and its visible tail) we bound.
  async function setUpUser(page: Page, label: string): Promise<{ address: string; tail: string }> {
    const email = uniqueEmail(label);
    await signUpViaPassword(page, email);
    await expect(page).toHaveURL(/\/connect(\b|\/|\?|$)/);

    await page.getByTestId("tier-free").click();
    await page.getByTestId("channel-telegram").click();

    const token = await readPairToken(page);

    const client = convexClient();
    const address = uniqueTelegramAddress(label);
    const result = await redeemTelegram(client, token, address);
    expect(result.ok, `bind for ${label} should succeed: ${result.reason ?? ""}`).toBe(
      true,
    );

    // The wizard flips to done reactively once the bind lands.
    await expect(page.getByTestId("step-done")).toBeVisible();

    return { address, tail: tail4(address) };
  }

  test("user A's dashboard shows A's channel and not B's", async ({ browser }) => {
    // Two fully separate browser contexts → two independent auth sessions.
    let ctxA: BrowserContext | null = null;
    let ctxB: BrowserContext | null = null;
    try {
      ctxA = await browser.newContext();
      ctxB = await browser.newContext();
      const pageA = await ctxA.newPage();
      const pageB = await ctxB.newPage();

      const userA = await setUpUser(pageA, "iso-a");
      const userB = await setUpUser(pageB, "iso-b");

      // Distinct tails so "not contains B" is a meaningful assertion.
      expect(userA.tail).not.toEqual(userB.tail);

      // 1) On A's dashboard: A's connection is present.
      await pageA.goto("/dashboard");
      const panelA = pageA.getByTestId("connections-panel");
      await expect(panelA).toBeVisible();
      // telegram channel listed, masked to A's tail.
      await expect(panelA.getByText(/telegram/i).first()).toBeVisible();
      await expect(panelA.getByText(new RegExp(userA.tail))).toBeVisible();

      // 2) A's panel must NOT contain B's address tail (no cross-tenant leak).
      await expect(panelA.getByText(new RegExp(userB.tail))).toHaveCount(0);
      const panelTextA = (await panelA.innerText()).toLowerCase();
      expect(panelTextA).not.toContain(userB.tail.toLowerCase());

      // 3) Symmetrically, B's dashboard shows B and not A.
      await pageB.goto("/dashboard");
      const panelB = pageB.getByTestId("connections-panel");
      await expect(panelB).toBeVisible();
      await expect(panelB.getByText(new RegExp(userB.tail))).toBeVisible();
      await expect(panelB.getByText(new RegExp(userA.tail))).toHaveCount(0);
      const panelTextB = (await panelB.innerText()).toLowerCase();
      expect(panelTextB).not.toContain(userA.tail.toLowerCase());
    } finally {
      await ctxA?.close();
      await ctxB?.close();
    }
  });
});
