import { test, expect } from "@playwright/test";

test.describe("landing page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("shows the wallpaper-led Amyris hero", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /^Amyris$/ })).toBeVisible();
    await expect(page.getByText(/ИИ который действительно полезен/i)).toBeVisible();
  });

  test("primary CTA opens iMessage", async ({ page }) => {
    const start = page.getByTestId("start-imessage");
    await expect(start).toBeVisible();
    await expect(start).toHaveText("Начать");
    await expect(start).toHaveAttribute("href", /^imessage:\/\//);
  });

  test("hero login links to phone registration", async ({ page }) => {
    const signIn = page.getByRole("link", { name: /^Войти$/ }).first();
    await expect(signIn).toBeVisible();
    await expect(signIn).toHaveAttribute("href", /\/signin$/);

    await signIn.click();
    await expect(page).toHaveURL(/\/signin(\b|\/|\?|$)/);
    await expect(page.getByTestId("signin-card")).toBeVisible();
    await expect(page.getByTestId("phone-input")).toBeVisible();
  });
});
