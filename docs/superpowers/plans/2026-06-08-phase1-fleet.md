# Phase 1 — Hermes Fleet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. This plan is grounded in measured Phase-0 constants (see `lab/REPORT.md`). Some early tasks contain DECISIONS that need the operator's input — marked `DECIDE`.

**Goal:** Turn the validated single-user lab into a multi-tenant product: a Sendblue iMessage number → TS/Convex router + control plane → a fleet of per-user Hermes containers (24/7) on GCP → MiniMax-M3, with real Instagram resolution and freemium quotas.

**Architecture (locked in design doc):** one service number (Sendblue) → router/control plane (users, billing, quotas, TCPA, suppression) → fleet orchestrator launching one Hermes container per user on shared GCE VMs → MiniMax-M3. Convex is the control plane only (cannot live inside Hermes — SQLite/files hardwired). The container image extends the Phase-0 `resolver-core` (already building in Artifact Registry: `us-central1-docker.pkg.dev/hermes-saved-content-lab/saved-content/resolver-core:lab`).

**Measured Phase-0 constants feeding this plan (from `lab/REPORT.md`):**
- RAM ≈ 290 MB (CLI) / est. 350–500 MB (persistent gateway) per instance → **~50–60 users / 32 GB host** (beats SC-008 target of 30). Re-measure the real gateway before committing density.
- Cost ≈ $0.006/text save, higher for video; ~$2–4/active-user/mo → within the $4.5 SC-005 ceiling for text-heavy use; **watch video volume**.
- Resolve: article (Jina) + X (fxtwitter) reliable & free; YouTube/TikTok need `--impersonate chrome` + curl_cffi (fixed in resolve.py, baked into the image); **Instagram needs a paid resolver — gates 99% of real usage**.

**GCP foundation already provisioned:** project `hermes-saved-content-lab` (#7700387935), billing linked, Cloud Build + Artifact Registry + Run + Storage enabled, AR repo `saved-content`, the resolver-core image built & tested in-cloud.

---

## Decisions needed first (operator)

- **DECIDE-1 — Instagram resolver vendor.** Options: ScrapeCreators (per-call API, simplest), Apify (actor-based, flexible), or cookie-based yt-dlp (free but fragile/ToS-risky, needs a logged-in IG session). Recommendation: start with ScrapeCreators for reels/carousels (cleanest API), keep yt-dlp+cookies as a fallback. Cost per IG resolve becomes a COGS line — measure it against the $9–13 price.
- **DECIDE-2 — iMessage vendor.** Sendblue (design default; AI Agent plan ~$100/line/mo) vs Blooio. First Phase-1 task is a live share-sheet→webhook test on whichever, before building on it.
- **DECIDE-3 — MiniMax key strategy.** The fleet needs a funded, metered MiniMax key (the lab key you gave was empty). Either a dedicated MiniMax API key with billing, or the Nous arrangement if it offers per-tenant metering. Required before real $/user numbers.

---

## Milestone A — Fleet container (extends resolver-core)

**A1. Fix `library.py` DB isolation (fleet-critical).** Default DB must be `$HERMES_HOME/saved-content/items.json` (not hardcoded `~/.hermes`). TDD: test that with `HERMES_HOME=/x` the default db path is `/x/saved-content/items.json`; keep `--db` override. (Latent bug found in Phase-0 e2e.)
**A2. Full fleet image.** Layer Hermes Agent onto the resolver-core Dockerfile: pin Hermes v0.11.0, install the saved-content skill at `$HERMES_HOME/skills/saved-content`, MiniMax-M3 provider config, IG resolver creds via env. Build via the existing cloudbuild pipeline.
**A3. Per-container config contract.** Each container gets: `HERMES_HOME` (its own volume), user id, MiniMax key, IG resolver key, and the Sendblue/router callback URL. Document the env contract.
**A4. IG resolver integration.** Add an `_instagram` path to resolve.py using the DECIDE-1 vendor (replace the yt-dlp IG attempt that hits the login wall). TDD with mocked vendor responses; one live smoke. Measure per-IG-resolve cost + success rate on real reels/carousels.

## Milestone B — Control plane (Convex) + router

**B1. Convex schema:** User, AgentInstance, Entitlement, UsageEvent, SuppressionRecord (from spec Key Entities). **B2. Router:** Sendblue inbound webhook → identify user → forward to their container; STOP-class suppression at the router (TCPA), quiet-hours 21:00–09:00, ≤2 proactive/day. **B3. Fleet orchestrator:** launch/stop/health-check per-user containers on GCE VMs; bin-pack by the measured RAM density; cold-start a container on first message. **B4. Quotas:** freemium 20 saves+10 actions free / 300+100 paid, metered via UsageEvent.

## Milestone C — Money + beta

**C1. Paddle (MoR) subscriptions** wired to Entitlement. **C2. Onboarding:** website button → provision a container → Sendblue pairing → first "привет". **C3. Closed beta** (10–20 friends); measure real $/user, RAM density, retention; tune resurfacing cadence/copy from real usage. **C4. Re-run the golden set with operator's REAL 20 bookmarks** for the true SC-001 gate.

## First live test (do before building on the vendor)
Sendblue (or Blooio) share-sheet → webhook round-trip: share an IG reel from iPhone, confirm the URL reaches a stub webhook. This is the go/no-go for the iMessage vendor (DECIDE-2).

---

## Self-review
- **Spec coverage:** US3 (one-click agent) → C2; US4 (actions w/ draft-confirm) → carried from lab SKILL, hardened in A2; US5 (freemium) → B4/C1. SC-005/008 re-validated in C3 with real fleet numbers.
- **Constants:** RAM/cost/density from REPORT.md drive B3 bin-packing and C1 pricing.
- **Open decisions** (DECIDE-1/2/3) are surfaced, not buried — they gate Milestones A/B and need the operator.
