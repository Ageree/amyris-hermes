import { Email } from "@convex-dev/auth/providers/Email";

// ---------------------------------------------------------------------------
// Email one-time-code provider (design §7 / §9): SMS-parity onboarding without a
// phone number. An 8-digit numeric code is emailed via the Resend REST API (no
// extra npm dep — plain fetch). 15-min TTL. The code has ~26.6 bits of entropy;
// combined with the verification-code single-use + TTL + Convex Auth's per-email
// rate limiting that is adequate for email delivery (an attacker would also need
// the inbox). AUTH_RESEND_KEY + AUTH_EMAIL_FROM live in Convex env (never code).
// Absent key => the email flow throws at send time; Password/Google still work.
// ---------------------------------------------------------------------------

const CODE_DIGITS = 8;
const TTL_SECONDS = 60 * 15;

export const ResendOTP = Email({
  id: "resend-otp",
  apiKey: process.env.AUTH_RESEND_KEY,
  maxAge: TTL_SECONDS,

  // High-entropy numeric code (rejection-free: each byte mod 10 is fine for an
  // 8-digit human-typable code; uniform enough given the single-use + TTL).
  async generateVerificationToken() {
    const bytes = new Uint8Array(CODE_DIGITS);
    crypto.getRandomValues(bytes);
    let code = "";
    for (const b of bytes) code += (b % 10).toString();
    return code;
  },

  async sendVerificationRequest({ identifier: email, provider, token }) {
    const apiKey = (provider as { apiKey?: string }).apiKey;
    if (!apiKey) throw new Error("AUTH_RESEND_KEY not configured");
    const from = process.env.AUTH_EMAIL_FROM ?? "assistant <onboarding@resend.dev>";

    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from,
        to: [email],
        subject: `your code is ${token}`,
        text: `your one-time code is ${token}\n\nit expires in 15 minutes. if you didn't ask to sign in, you can ignore this.`,
      }),
    });

    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`resend send failed: ${res.status} ${body}`.trim());
    }
  },
});
