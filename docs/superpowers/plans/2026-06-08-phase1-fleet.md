# Phase 1 — Browser-First Assistant Fleet (Roadmap)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. This is the **decomposed roadmap** — each sub-plan (P1A…P1E) is its own bite-sized plan file and produces working, testable software on its own. Reworked 2026-06-08 around the pivot ([[../specs/2026-06-08-general-assistant-pivot.md]]): the **real browser is the core capability**, not a paid IG resolver.

**Goal:** Turn the validated single-user lab into a multi-tenant, browser-first personal assistant: a Sendblue iMessage number → TS/Convex router + control plane → a fleet of per-user Hermes containers (24/7, each with a real logged-in browser) on GCP → MiniMax-M3, with freemium quotas.

**Architecture (locked in design doc + delta):** one service number (Sendblue) → router/control plane (users, billing, quotas, TCPA, suppression) → fleet orchestrator launching one Hermes container per user on shared GCE VMs → MiniMax-M3. Each container carries the **browser toolset (two lanes)**. Convex is the control plane only (cannot live inside Hermes — SQLite/files hardwired). The image extends the Phase-0 `resolver-core` (`us-central1-docker.pkg.dev/hermes-saved-content-lab/saved-content/resolver-core:lab`).

**Measured Phase-0 constants (from `lab/REPORT.md`):**
- RAM ≈ 290 MB (CLI) / est. 350–500 MB (persistent gateway) per instance → **~50–60 users / 32 GB host**. Browser adds load — **re-measure with a live browser session before committing density.**
- Cost ≈ $0.006/text save; ~$2–4/active-user/mo for text-heavy use; **watch video + browser-vision token volume** (M3 multimodal on screenshots/frames is the new cost driver, replacing per-IG-resolve API fees).
- Resolve: article (Jina) + X (fxtwitter) reliable & free; YouTube/TikTok need `--impersonate chrome`; **Instagram/login-walled content → solved by the logged-in browser (Lane A), not a paid vendor.**

**GCP foundation already provisioned:** project `hermes-saved-content-lab` (#7700387935), billing linked, Cloud Build + Artifact Registry + Run + Storage enabled, AR repo `saved-content`, `resolver-core` image built & tested in-cloud.

---

## Decisions — status 2026-06-08 (all pivot decisions resolved; see design-delta §5)

- **DECIDE-1 — IG resolver vendor. SUPERSEDED → browser-first.** No paid IG resolver for the common case. Public/no-login content keeps the cheap fast path (yt-dlp / fxtwitter / Jina); login-walled or action-requiring content goes through the **logged-in browser** (Lane A / Camofox persistent profile). Per-resolve API fee → replaced by browser compute + M3 multimodal tokens. (Keep a paid resolver only as an optional last-resort fallback, not a v1 dependency.)
- **DECIDE-2 — iMessage vendor. RESOLVED → Sendblue.** Shared number created; API keys live-verified 2026-06-08 (`sb-api-key-id`/`sb-api-secret-key`, see [[sendblue-api-reference]]).
- **DECIDE-3 — Fleet MiniMax key. OPEN (operator).** Personal key (~$24 balance) is fine for dev; the fleet needs a **funded, metered** MiniMax key for real $/user. Decide: reuse personal key vs. dedicated billed key. Not a blocker for P1A/P1B dev.
- **Composio. DEFERRED post-v1 (opt-in).** Verified dead end on the dev `ak_` key (MCP runtime 401); decoupled from v1. One-command opt-in `bash ~/.hermes-savedlab/enable-composio.sh`. See [[composio-for-hermes]]. The browser covers the same connector ground for v1.

---

## Sub-plans (each is its own bite-sized plan file; build in order)

### ▶ P1A — Walking skeleton (single-user, LIVE)  → `2026-06-08-phase1a-walking-skeleton.md`
The thinnest end-to-end slice that proves the *pivoted* architecture live: **you iMessage the Sendblue number → router → a browser-equipped Hermes container (M3) does ONE real browser action → reply lands back on your iPhone.** No Convex, no quotas, no fleet — one hard-wired user. This is the go/no-go gate for everything else. Reuses Sendblue (resolved) + the de-risked browser stack (Lane B on local Chrome). **First live test of the whole spine.**

### P1B — Browser, two lanes, hardened  → `phase1b-browser-lanes.md` (next to author)
- **Lane A (Camofox):** `managed_persistence` per-user persistent profile; the "log in once → agent acts inside" UX (VNC live-view handoff); cookies survive restarts, isolated per `HERMES_HOME`.
- **Lane B (browser-harness + Browserbase):** swap local Chrome for a Browserbase `wss://` session (`BU_CDP_WS`); enable `BH_DOMAIN_SKILLS=1` so per-site skills accumulate per user.
- **Saved-content becomes browser-first:** resolve reels/TikTok via the logged-in browser + M3 vision/native-video, public content via the cheap fast path. Retain cards + spaced resurfacing from the lab skill.

### P1C — Control plane (Convex) + router
Convex schema: User, AgentInstance, Entitlement, UsageEvent, SuppressionRecord (spec Key Entities). Router: Sendblue inbound webhook → identify user → forward to their container; STOP-class suppression at the router (TCPA), quiet-hours 21:00–09:00, ≤2 proactive/day.

### P1D — Fleet orchestrator + quotas
Launch/stop/health-check per-user containers on GCE VMs; bin-pack by measured (browser-inclusive) RAM density; cold-start on first message. Freemium quotas (20 saves+10 actions free / 300+100 paid) metered via UsageEvent.

### P1E — Money + beta
Paddle (MoR) subscriptions → Entitlement. Onboarding: website button → provision container → Sendblue pairing → first "привет". Closed beta (10–20 friends); measure real $/user, RAM density, retention; re-run the golden set with the operator's REAL 20 bookmarks (true SC-001 gate).

---

## Operator inputs by sub-plan (gather ahead — see session manifest)
- **P1A:** a test iMessage from your iPhone to the shared number; possibly paste one webhook URL into the Sendblue dashboard (only if not API-settable).
- **P1B:** Browserbase API key + Project ID (`browserbase.com`); a one-time login to whatever site you want the agent to act in (Lane A).
- **P1C:** Convex login (`convex.dev`, GitHub/Google) when standing up the control plane.
- **P1D:** confirm GCP billing active on `hermes-saved-content-lab`; DECIDE-3 funded MiniMax key.
- **P1E:** Paddle seller account (`paddle.com` — note: business verification has lead time, start early).
- **Hygiene (any time):** rotate + resend MiniMax + Sendblue keys (were in transcript).

## Self-review
- **Spec coverage:** US1/US2 (saved-content) → P1B; US3 (one-click agent) → P1E onboarding; US4 (actions w/ draft-confirm) → P1A (skeleton action) + P1B (real lanes); US5 (freemium) → P1D/P1E. SC-005/008 re-validated in P1E with real fleet numbers.
- **Pivot consistency:** DECIDE-1 demoted to browser-first everywhere; no v1 dependency on a paid IG vendor or on Composio.
- **Decomposition:** five sub-plans, each independently testable; P1A is a complete live slice, not a horizontal layer.
