import { convexAuth } from "@convex-dev/auth/server";
import Google from "@auth/core/providers/google";
import { Password } from "@convex-dev/auth/providers/Password";
import type { MutationCtx } from "./_generated/server";
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
  providers: [
    Google,
    Password({
      id: "password",
      // The provider otherwise accepts ANY non-empty string. Minimal strength gate.
      validatePasswordRequirements: (password: string) => {
        if (password.length < 8) {
          throw new Error("password must be at least 8 characters");
        }
      },
    }),
    ResendOTP,
  ],
  callbacks: {
    // Dedupe by email and seed app fields + entitlement on first sign-in — but ONLY
    // when email ownership is PROVEN. A bare credentials (password) sign-up can
    // assert ANY email; deduping it into an existing row would hand the attacker
    // that account (including the operator's — the takeover hole). So we:
    //   - link to an existing row ONLY for verified sign-ins (oauth/email/verification),
    //   - REJECT an unverified sign-up whose email already belongs to an account,
    //   - set isOperator ONLY from a PROVEN operator email.
    async createOrUpdateUser(ctx, { existingUserId, type, profile }) {
      // Account already linked to a user (re-sign-in) — keep it, write nothing new.
      if (existingUserId) return existingUserId;

      // convex-auth types this callback's ctx as GenericMutationCtx<AnyDataModel>
      // (provider-agnostic), so ctx.db.query("users").withIndex("email") wouldn't
      // see our schema's `email` index. Re-type to OUR generated MutationCtx — at
      // runtime it IS a mutation ctx for this deployment, so this is sound.
      const db = (ctx as unknown as MutationCtx).db;
      const email = normalizeEmail(profile.email);

      // Email ownership is proven by an OAuth provider (unless it explicitly returns
      // emailVerified:false), by the email OTP provider, or by a post-token
      // verification. A plain "credentials" (password) sign-up proves nothing.
      const emailProven =
        type === "email" ||
        type === "verification" ||
        (type === "oauth" && profile.emailVerified !== false);

      // Cross-provider dedupe — link to an existing row ONLY when proven. An
      // unverified sign-up to a taken email is refused (no squatting / takeover).
      if (email) {
        const byEmail = await db
          .query("users")
          .withIndex("email", (q) => q.eq("email", email))
          .first();
        if (byEmail) {
          if (emailProven) return byEmail._id;
          throw new Error(
            "an account with this email already exists — sign in instead",
          );
        }
      }

      // isOperator (user #0, unlimited) is set ONLY from a proven operator email.
      const isOperator = emailProven && email === OPERATOR_EMAIL;
      const now = Date.now();
      const userId = await db.insert("users", {
        email,
        name: typeof profile.name === "string" ? profile.name : undefined,
        image: typeof profile.image === "string" ? profile.image : undefined,
        isOperator,
        tier: isOperator ? "max" : "free",
        createdAt: now,
      });

      // Source-of-truth entitlement (free instant; operator → max + unlimited).
      await grantSignupEntitlement(ctx as unknown as MutationCtx, userId, isOperator);
      return userId;
    },
  },
});
