import { defineConfig, devices } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// E2E config for the hermes-fleet web app.
//
// Next.js loads .env.local automatically for the dev server (so the app gets
// NEXT_PUBLIC_CONVEX_URL etc.). The TESTS run in this Node process, which does
// NOT auto-load .env.local — so we forward the two values the specs need
// (NEXT_PUBLIC_CONVEX_URL + WORKER_SECRET) into `use.env`-free globals via
// process.env, falling back to the same .env.local the app reads. We deliberately
// avoid an arbitrary sleep anywhere; specs wait on explicit expect(...) conditions.

const PORT = 3000;
const BASE_URL = `http://localhost:${PORT}`;

// ESM-safe __dirname (the config is loaded as ESM: package.json has "type":"module").
const HERE = dirname(fileURLToPath(import.meta.url));

// Minimal .env.local reader: Playwright's config + the TEST process don't get
// Next's env injection (only the dev server does). We read the keys the specs
// rely on (NEXT_PUBLIC_CONVEX_URL, optionally WORKER_SECRET) so `convexClient()`
// can reach the dev deployment even when they aren't exported in the shell.
function loadEnvLocal(): void {
  const file = resolve(HERE, ".env.local");
  if (!existsSync(file)) return;
  const raw = readFileSync(file, "utf8");
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = trimmed.slice(eq + 1).trim();
    // Don't clobber values already present in the environment (shell wins).
    if (process.env[key] === undefined) process.env[key] = value;
  }
}

loadEnvLocal();

export default defineConfig({
  testDir: "./e2e",
  // One signup/connect flow at a time keeps the dev Convex deployment calm and
  // makes the reactive assertions deterministic.
  fullyParallel: false,
  workers: 1,
  // Don't allow a stray `test.only` to silently shrink a CI run.
  forbidOnly: !!process.env.CI,
  retries: 0,
  // Generous: a cold Next dev compile + a Convex round-trip can take a while.
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? "github" : "list",

  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Headless by default; PWDEBUG/--headed still works locally.
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: {
    command: "npm run dev",
    url: BASE_URL,
    reuseExistingServer: true,
    // First `next dev` compile can be slow on a cold cache.
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
    env: {
      // Forward what the app needs; Next also reads .env.local itself, but being
      // explicit means a shell-exported value wins consistently.
      ...(process.env.NEXT_PUBLIC_CONVEX_URL
        ? { NEXT_PUBLIC_CONVEX_URL: process.env.NEXT_PUBLIC_CONVEX_URL }
        : {}),
    },
  },
});
