import { test, expect } from "@playwright/test";
import {
  uniqueEmail,
  signUpViaPassword,
  convexClient,
  readPairToken,
  redeemTelegram,
  uniqueTelegramAddress,
} from "./helpers";

// Dashboard user stories (WEB-21/22/23/24/25) exercised end-to-end against the
// live dev deployment via throwaway password signups. Each test signs up a fresh
// @example.com user, so there is no cross-test state. The disconnect test needs
// the WORKER_SECRET-gated bind wrapper; the rest are pure UI and run unconditionally.

test.describe("dashboard", () => {
  // WEB-21 (shell: three panels + exactly one h1) + WEB-22 (topbar email + sign-out).
  test("shows the three panels, the account email, and signs out cleanly", async ({ page }) => {
    const email = uniqueEmail("dash");
    await signUpViaPassword(page, email);

    await page.goto("/dashboard");

    // WEB-21: the three dashboard panels render, and there is exactly one h1.
    await expect(page.getByTestId("tier-card")).toBeVisible();
    await expect(page.getByTestId("usage-panel")).toBeVisible();
    await expect(page.getByTestId("connections-panel")).toBeVisible();
    await expect(page.locator("h1")).toHaveCount(1);

    // WEB-22: the signed-in email appears in the top bar, then sign-out redirects
    // home with no uncaught error. (The TopBar <header> is nested in <main>, so it
    // is NOT a `banner` landmark — scope by the header element directly.)
    await expect(page.locator("header").getByText(email)).toBeVisible();

    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.getByRole("button", { name: /sign out/i }).click();
    await page.waitForURL(/\/$|\/(?:\?|#|$)/, { timeout: 30_000 });
    expect(errors, `no uncaught error on sign-out: ${errors.join("; ")}`).toHaveLength(0);
  });

  // WEB-23: a free user sees upgrade buttons; clicking one (stub checkout, no http
  // url) surfaces the coming-soon banner rather than navigating away.
  test("free user can start an upgrade and sees the coming-soon banner", async ({ page }) => {
    await signUpViaPassword(page, uniqueEmail("dash-up"));
    await page.goto("/dashboard");

    const card = page.getByTestId("tier-card");
    const upgradePro = card.getByRole("button", { name: /upgrade to pro/i });
    await expect(upgradePro).toBeVisible();
    await expect(card.getByRole("button", { name: /upgrade to max/i })).toBeVisible();

    await upgradePro.click();

    // Stub checkout returns no http url → a role=status banner, no off-site nav.
    await expect(card.getByRole("status")).toContainText(/launching soon|coming soon|free for now/i);
    await expect(page).toHaveURL(/\/dashboard/);
  });

  // WEB-24: the usage meter renders a progressbar reflecting the live free-tier
  // quota (100) with the matching "N left" count. (Danger-threshold + unlimited
  // branches are pure display logic, not seeded here.)
  test("usage panel renders a progressbar matching the free quota", async ({ page }) => {
    await signUpViaPassword(page, uniqueEmail("dash-usage"));
    await page.goto("/dashboard");

    const bar = page.getByTestId("usage-panel").getByRole("progressbar");
    await expect(bar).toBeVisible();
    await expect(bar).toHaveAttribute("aria-valuemin", "0");
    await expect(bar).toHaveAttribute("aria-valuenow", "0");

    const max = await bar.getAttribute("aria-valuemax");
    expect(Number(max)).toBeGreaterThan(0);
    // A brand-new user has used 0, so "left" == quota.
    await expect(page.getByTestId("usage-panel")).toContainText(new RegExp(`${max}\\s*left`));
  });

  // WEB-25 (empty state): a user with no channels sees the empty state + a
  // "connect a channel" link pointing at the channel step of the wizard.
  test("empty connections state links to the channel step", async ({ page }) => {
    await signUpViaPassword(page, uniqueEmail("dash-empty"));
    await page.goto("/dashboard");

    const panel = page.getByTestId("connections-panel");
    const link = panel.getByRole("link", { name: /connect a channel/i });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", /\/connect\?step=channel/);
  });

  // WEB-25 (disconnect): bind a telegram channel, then disconnect it from the
  // dashboard and assert the row reactively disappears + a polite announcement.
  test("disconnecting a channel reactively removes its row", async ({ page }) => {
    test.skip(
      !process.env.WORKER_SECRET,
      "requires WORKER_SECRET to call the testing:* bind wrapper",
    );

    await signUpViaPassword(page, uniqueEmail("dash-disc"));
    await expect(page).toHaveURL(/\/connect(\b|\/|\?|$)/);
    await page.getByTestId("tier-free").click();
    await page.getByTestId("channel-telegram").click();

    const token = await readPairToken(page);
    const address = uniqueTelegramAddress("dash-disc");
    const tail = address.slice(-4);
    const result = await redeemTelegram(convexClient(), token, address);
    expect(result.ok, `bind should succeed: ${result.reason ?? ""}`).toBe(true);
    await expect(page.getByTestId("step-done")).toBeVisible();

    await page.goto("/dashboard");
    const panel = page.getByTestId("connections-panel");
    await expect(panel.getByText(new RegExp(tail))).toBeVisible();

    await panel.getByRole("button", { name: /disconnect/i }).click();

    // The row disappears reactively (the myChannels subscription updates). The
    // success announcement lives in an sr-only region INSIDE that same row, so it
    // unmounts with the row — the reactive removal is the assertable behavior.
    await expect(panel.getByText(new RegExp(tail))).toHaveCount(0);
  });
});
