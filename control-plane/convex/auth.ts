import { convexAuth } from "@convex-dev/auth/server";
import Google from "@auth/core/providers/google";
import { Password } from "@convex-dev/auth/providers/Password";
import { ResendOTP } from "./ResendOTP";
import { grantSignupEntitlement } from "./billing/grant";

// ---------------------------------------------------------------------------
// Convex Auth (design §9). Three providers, all deduped to ONE users row per
// email by the createOrUpdateUser callback (so signing in with Google then later
// the email code does NOT create a second account):
//   - Google        — primary OAuth (needs AUTH_GOOGLE_ID / AUTH_GOOGLE_SECRET)
//   - Password       — email+password; self-contained, powers autonomous e2e
//   - ResendOTP      — 8-digit email code, SMS-parity onboarding (needs AUTH_RESEND_KEY)
// A provider with absent creds only breaks ITS OWN flow at runtime; sign-in
// session issuance depends on JWT_PRIVATE_KEY/JWKS (set in Convex env, §9).
//
// On first creation the callback sets the app fields the rest of the system reads:
// isOperator (the operator's email → user #0, unlimited), the denormalized tier
// mirror, and the source-of-truth `entitlements` row (free instant; operator max).
// Identity is ALWAYS the JWT subject — no function ever takes a client `userId`.
// ---------------------------------------------------------------------------

// Operator = user #0 (zero-downtime migration, design §10). Matched case-insensitively.
export const OPERATOR_EMAIL = "nikto256@gmail.com";

function normalizeEmail(raw: unknown): string | undefined {
  if (typeof raw !== "string") return undefined;
  const e = raw.trim().toLowerCase();
  return e.length > 0 ? e : undefined;
}

export const { auth, signIn, signOut, store, isAuthenticated } = convexAuth({
  providers: [Google, Password({ id: "password" }), ResendOTP],
  callbacks: {
    // Dedupe by email and seed app fields + entitlement on first sign-in.
    async createOrUpdateUser(ctx, { existingUserId, profile }) {
      // Account already linked to a user (re-sign-in) — keep it, write nothing new.
      if (existingUserId) return existingUserId;

      const email = normalizeEmail(profile.email);

      // Cross-provider dedupe: an email already on a users row (incl. the
      // operator row pre-seeded by the backfill) wins — link this account to it.
      if (email) {
        const byEmail = await ctx.db
          .query("users")
          .withIndex("email", (q) => q.eq("email", email))
          .first();
        if (byEmail) return byEmail._id;
      }

      const isOperator = email === OPERATOR_EMAIL;
      const now = Date.now();
      const userId = await ctx.db.insert("users", {
        email,
        name: typeof profile.name === "string" ? profile.name : undefined,
        image: typeof profile.image === "string" ? profile.image : undefined,
        isOperator,
        tier: isOperator ? "max" : "free",
        createdAt: now,
      });

      // Source-of-truth entitlement (free instant; operator → max + unlimited).
      await grantSignupEntitlement(ctx, userId, isOperator);
      return userId;
    },
  },
});
