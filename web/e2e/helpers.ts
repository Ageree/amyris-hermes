import { expect, type Page } from "@playwright/test";
import { ConvexHttpClient } from "convex/browser";
import { makeFunctionReference } from "convex/server";

// ─────────────────────────────────────────────────────────────────────────────
// Shared e2e helpers. Lowercase-voice app, dark "calm terminal" UI. These wrap
// the few cross-cutting moves: minting a unique identity, signing up through the
// password form, building a Convex HTTP client for the test-only wrappers, and
// reading the raw pairing token the wizard exposes.
// ─────────────────────────────────────────────────────────────────────────────

const DEFAULT_PASSWORD = "e2e-Passw0rd!";

/** A collision-proof email for a brand-new account on each run. */
export function uniqueEmail(prefix = "e2e"): string {
  const stamp = Date.now().toString(36);
  const rand = Math.random().toString(36).slice(2, 8);
  return `${prefix}+${stamp}${rand}@example.com`;
}

/** The default password used by signUpViaPassword when none is supplied. */
export function defaultPassword(): string {
  return DEFAULT_PASSWORD;
}

/**
 * Sign up a fresh user via the email+password form on /signin.
 *
 * Flips the flow toggle to "sign up", fills the credentials, submits, and waits
 * for the post-auth route (the SignInCard pushes to /connect; /dashboard is also
 * accepted in case middleware bounces an already-connected user there).
 */
export async function signUpViaPassword(
  page: Page,
  email: string,
  password: string = DEFAULT_PASSWORD,
): Promise<void> {
  await page.goto("/signin");

  const card = page.getByTestId("signin-card");
  await expect(card).toBeVisible();

  // The card starts in "sign in" flow. Flip to "sign up" via the explicit tab.
  const toSignUp = card.getByTestId("tab-signup");
  await expect(toSignUp).toBeVisible();
  await toSignUp.click();

  // Email + password is now the only form on the card.
  const pwForm = card.locator('form:has(input[type="password"])');
  await expect(pwForm).toBeVisible();

  // In sign-up mode the submit button reads "create account".
  const submit = pwForm.getByRole("button", { name: /^create account$/i });
  await expect(submit).toBeVisible();

  // Fill the credentials within the password form.
  await pwForm.locator('input[type="email"]').fill(email);
  await pwForm.locator('input[type="password"]').fill(password);

  await expect(submit).toBeEnabled();
  await submit.click();

  // SignInCard.handlePassword routes to /connect on success. Accept /dashboard
  // too (middleware may bounce). Wait on the URL, not an arbitrary sleep.
  await page.waitForURL(/\/(connect|dashboard)(\b|\/|\?|$)/, { timeout: 30_000 });
}

/**
 * A Convex HTTP client pointed at the dev deployment. Used to drive the
 * double-gated testing:* wrappers (which require WORKER_SECRET) from Node.
 *
 * Throws a clear error if NEXT_PUBLIC_CONVEX_URL is missing so a misconfigured
 * run fails loudly instead of silently hitting the wrong backend.
 */
export function convexClient(): ConvexHttpClient {
  const url = process.env.NEXT_PUBLIC_CONVEX_URL;
  if (!url) {
    throw new Error(
      "NEXT_PUBLIC_CONVEX_URL is not set — cannot build a Convex client for e2e.",
    );
  }
  return new ConvexHttpClient(url);
}

/** The shared worker secret that double-gates the testing:* wrappers. */
export function workerSecret(): string {
  const secret = process.env.WORKER_SECRET;
  if (!secret) {
    throw new Error(
      "WORKER_SECRET is not set — the testing:* convex wrappers cannot be called.",
    );
  }
  return secret;
}

/**
 * Redeem a telegram pairing token via the test-only convex wrapper, simulating
 * the bot bind without a real bot. Returns the wrapper's result.
 */
export async function redeemTelegram(
  client: ConvexHttpClient,
  token: string,
  address: string,
): Promise<{ ok: boolean; userId: string | null; idempotent?: boolean; reason?: string }> {
  const ref = makeFunctionReference<
    "mutation",
    { workerSecret: string; token: string; address: string },
    { ok: boolean; userId: string | null; idempotent?: boolean; reason?: string }
  >("testing:testRedeemTelegram");
  const args = {
    workerSecret: workerSecret(),
    token,
    address,
  };

  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      return await client.mutation(ref, args);
    } catch (error) {
      if (!isTransientConvexFetch(error) || attempt === 2) throw error;
      await new Promise((resolve) => setTimeout(resolve, 400 * (attempt + 1)));
    }
  }

  throw new Error("unreachable: redeemTelegram retry loop exhausted");
}

function isTransientConvexFetch(error: unknown): boolean {
  const message = String(error instanceof Error ? error.message : error);
  const cause = error instanceof Error && "cause" in error ? String(error.cause) : "";
  return /fetch failed|socket disconnected|ECONNRESET|ETIMEDOUT|EAI_AGAIN|502|503|504/i.test(
    `${message} ${cause}`,
  );
}

/**
 * Read the raw pairing token the wizard exposes as data-testid="pair-token".
 *
 * The element is rendered `hidden`, so we read the token from its data-token
 * attribute (present on a hidden node) rather than its visible text. We wait for
 * the pairing-panel to attach first so the token is guaranteed minted.
 */
export async function readPairToken(page: Page): Promise<string> {
  await expect(page.getByTestId("pairing-panel")).toBeVisible();

  const tokenEl = page.getByTestId("pair-token");
  // attached (not visible — it's hidden by design) is the right wait here.
  await tokenEl.waitFor({ state: "attached" });

  const token =
    (await tokenEl.getAttribute("data-token")) ??
    (await tokenEl.textContent())?.trim() ??
    "";

  expect(token, "pair token should be a non-empty string").not.toEqual("");
  return token;
}

/**
 * A telegram-ish address whose last 4 characters are unique per call, so the
 * dashboard's tail-mask ("••• <last4>") is distinguishable between tenants.
 */
export function uniqueTelegramAddress(prefix = "tg"): string {
  // 8 hex chars → the dashboard masks to the last 4, which we assert on.
  const tail = Math.random().toString(16).slice(2, 10).padEnd(8, "0");
  return `${prefix}_${Date.now().toString(36)}_${tail}`;
}
