# GOAL — Full multi-tenancy for the Hermes Fleet assistant

## Objective
Turn the LIVE single-user assistant into a real multi-tenant product:
landing page → signup/login (Convex Auth) → pick tier (free + paid; free instant,
paid stubbed) → press a button → deep-link into **iMessage OR Telegram** → a
per-user, **isolated** assistant that just works. Add **Telegram** (Bot API 10.1
HTML formatting) as a second channel beside Sendblue iMessage. Run each user in
their **own Hermes container on a GCP fleet**. Keep the operator (+79217818876)
answering with **ZERO downtime** throughout.

## Locked operator decisions (design to THESE)
1. Execution = per-user container fleet on GCP.
2. Billing = stubbed (free fully live; paid behind a provider-adapter; payment wired later).
3. Channels = BOTH iMessage + Telegram on ALL tiers; user picks at connect.
4. Auth = Convex Auth (built-in).
5. Telegram = Bot API 10.1 HTML formatting.

## Source of truth
- Design (authoritative): `docs/superpowers/specs/2026-06-14-multitenancy-design.md`
- Phased plan (M0–M7): `docs/superpowers/plans/2026-06-14-multitenancy-plan.md`
- Acceptance criteria: `./acceptance.md` (this dir)

## Constraints
- Additive-then-tighten Convex schema; NEVER break the brain contract
  (`messages:*`/`intents:*` WORKER_SECRET fns) or the live operator.
- TDD; the lab suite (≥208 green) is a non-decreasing floor at every phase boundary.
- Index discipline (no `.filter()` scans); object-form Convex fns with arg+return validators.
- Many small files; comprehensive error handling + boundary validation; no hardcoded secrets.
- Per-tenant isolation is a hard requirement (invariants A1–A4, design §1/§8).

## Operator inputs needed for LIVE legs only (the build proceeds without them)
- **Telegram**: bot token + username (BotFather) + a `TELEGRAM_WEBHOOK_SECRET` → M3 live + M4 deep links.
- **Domain**: Vercel domain for `web/` → M4 prod OAuth redirect / Convex `SITE_URL` (dev uses localhost).
- **GCP**: go-ahead + region (default `us-central1`) → M6 real fleet + operator cutover.

Defaults adopted autonomously (operator can override mid-flight by editing this file):
prices $19 Pro / $49 Max + quotas 100/1000/5000 turns; operator email
`nikto256@gmail.com`; unknown-sender = hint-once + per-address cooldown;
email-OTP via a Resend test sender in dev; the 6 pending key rotations stay deferred.

## The floor (run any time)
`cd lab && python3 -m pytest -q`  → ≥ 208 passed, 0 failed.
Full per-phase criteria + verify commands live in `acceptance.md`.
