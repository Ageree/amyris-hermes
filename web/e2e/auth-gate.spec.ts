import { test, expect } from "@playwright/test";

// Middleware (design §7) gates /dashboard and /connect: an unauthenticated
// visitor is redirected to /signin. The auth check reads the verified JWT from
// request cookies, so a fresh browser context (no cookies) is always unauthed.
// No Convex writes here — these assertions are fully deterministic.

test.describe("auth gate (unauthenticated)", () => {
  test("/dashboard redirects to /signin", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/signin(\b|\/|\?|$)/);
    // The sign-in surface is actually rendered, not just a URL change.
    await expect(page.getByTestId("signin-card")).toBeVisible();
  });

  test("/connect redirects to /signin", async ({ page }) => {
    await page.goto("/connect");
    await expect(page).toHaveURL(/\/signin(\b|\/|\?|$)/);
    await expect(page.getByTestId("signin-card")).toBeVisible();
  });
});
