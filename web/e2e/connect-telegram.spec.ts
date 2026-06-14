import { test, expect } from "@playwright/test";
import {
  uniqueEmail,
  signUpViaPassword,
  convexClient,
  readPairToken,
  redeemTelegram,
  uniqueTelegramAddress,
} from "./helpers";

// End-to-end pairing happy path for telegram. We drive the real UI through the
// wizard, mint a pairing token, then SIMULATE the bot bind by calling the
// double-gated testing:testRedeemTelegram wrapper from Node (no real bot). The
// payoff: the wizard flips to the connected state REACTIVELY (the myChannels
// subscription updates) — with NO page reload.
//
// Skipped when WORKER_SECRET is absent, since the wrapper is gated by it.
test.describe("connect telegram (reactive pairing)", () => {
  test.skip(
    !process.env.WORKER_SECRET,
    "requires WORKER_SECRET to call the testing:* convex wrappers",
  );

  test("wizard flips to 'connected' the instant the bind lands", async ({ page }) => {
    const email = uniqueEmail("tg");

    // 1) fresh account → lands on /connect.
    await signUpViaPassword(page, email);
    await expect(page).toHaveURL(/\/connect(\b|\/|\?|$)/);

    // 2) pick the free tier (first wizard step).
    const freeTier = page.getByTestId("tier-free");
    await expect(freeTier).toBeVisible();
    await freeTier.click();

    // 3) choose telegram on the channel step.
    const telegram = page.getByTestId("channel-telegram");
    await expect(telegram).toBeVisible();
    await telegram.click();

    // 4) the pairing panel renders and exposes the raw token.
    await expect(page.getByTestId("pairing-panel")).toBeVisible();
    const token = await readPairToken(page);

    // Sanity: we have NOT yet reached the done state.
    await expect(page.getByTestId("step-done")).toHaveCount(0);

    // 5) simulate the telegram bind out-of-band via the convex test wrapper.
    const client = convexClient();
    const address = uniqueTelegramAddress("tg");
    const result = await redeemTelegram(client, token, address);
    expect(result.ok, `redeemTelegram should succeed: ${result.reason ?? ""}`).toBe(
      true,
    );

    // 6) the wizard flips to "you're connected" REACTIVELY — no reload. The
    //    myChannels subscription updates and the effect advances to "done".
    const done = page.getByTestId("step-done");
    await expect(done).toBeVisible();
    // The connected copy lives inside the done card (scope to it; the wizard
    // heading also says "you're connected", which would be ambiguous unscoped).
    await expect(done.getByText(/you'?re connected/i)).toBeVisible();

    // The done card offers a route to the dashboard.
    await expect(page.getByTestId("done-dashboard")).toBeVisible();
  });
});
