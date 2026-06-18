import { test, expect } from "@playwright/test";

// Public marketing landing — no auth, no Convex writes. Asserts the three tier
// labels, both channel words, and a working "sign in" affordance. All matchers
// are case-insensitive to respect the lowercase voice without being brittle.

test.describe("landing page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("shows the three tier labels in the pricing grid", async ({ page }) => {
    // Scope to the pricing section so we match the tier CARDS, not incidental
    // copy elsewhere on the page.
    const pricing = page.locator("#pricing");
    await expect(pricing).toBeVisible();

    for (const label of ["free", "pro", "max"]) {
      await expect(
        pricing.getByText(new RegExp(`^${label}$`, "i")).first(),
      ).toBeVisible();
    }
  });

  test("mentions both channels (imessage + telegram)", async ({ page }) => {
    // Both words appear in the hero and as per-tier channel badges. We only
    // require them to be present somewhere on the public page.
    await expect(page.getByText(/imessage/i).first()).toBeVisible();
    await expect(page.getByText(/telegram/i).first()).toBeVisible();
  });

  test("has a sign-in affordance linking to /signin", async ({ page }) => {
    // The nav exposes a plain "sign in" link. Scope to the header so the
    // (also valid) footer "sign in" link doesn't make this ambiguous.
    const signIn = page.locator("header").getByRole("link", { name: /^sign in$/i });
    await expect(signIn).toBeVisible();
    await expect(signIn).toHaveAttribute("href", /\/signin$/);

    // And it actually navigates to the sign-in surface.
    await signIn.click();
    await expect(page).toHaveURL(/\/signin(\b|\/|\?|$)/);
    await expect(page.getByTestId("signin-card")).toBeVisible();
  });

  test("the primary 'get started' CTA begins agent creation at /signin", async ({ page }) => {
    // The redesigned hero leads with a single "get started" button — the entry
    // point to creating an assistant. It must reach the sign-in surface.
    const getStarted = page
      .locator("main")
      .getByRole("link", { name: /^get started$/i })
      .first();
    await expect(getStarted).toBeVisible();
    await expect(getStarted).toHaveAttribute("href", /\/signin$/);

    await getStarted.click();
    await expect(page).toHaveURL(/\/signin(\b|\/|\?|$)/);
    await expect(page.getByTestId("signin-card")).toBeVisible();
  });
});
