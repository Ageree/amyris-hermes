# Design: Personal Saved-Content Agent ("Hermes Fleet")

Date: 2026-06-07 · Status: approved-with-amendments (hosting → GCP) · Author: brainstorming session

## 1. Problem & Goal

Saved posts die in bookmarks. Users save IG reels, TikToks, X threads, articles —
and never return to them. The product turns "save" into "send to your agent":
a personal AI agent that lives in iMessage, understands every saved item,
resurfaces it at the right moment, and acts on it (plans, calendar, research;
transactions later).

Reference product: Poke (poke.com) — but Poke's входная ценность = email/calendar;
наша = сохранёнки. Business goal: a few thousand USD MRR; freemium, paid tier
$9–13/mo. Audience: non-technical iPhone users. Zero apps: onboarding = pay/start
on a landing page, everything else happens in iMessage.

## 2. The one-sentence architecture

**One service iMessage number → thin router → a fleet of always-on personal
Hermes agents (one Docker container per user) on GCP → MiniMax M2.7 API (the current MiniMax flagship; earlier specs said "M3", which does not exist — M2.7 is the real latest model as of 2026-06).**
Control plane (users, billing, quotas, fleet map) = Convex + TypeScript.

Each user gets a REAL personal agent: own memory, own self-improving skills,
own playbook, own cron schedule — Hermes used exactly as designed
(single-operator), multiplied by N containers. No multi-tenant rewriting of
Hermes internals.

```
iPhone user ──iMessage──▶ Sendblue (one service number)
                             │ webhook (signed)
                      ROUTER + CONTROL PLANE (TS on Convex)
                      users · billing(Paddle) · quotas · fleet map · TCPA
                             │ HTTP → Hermes API server (/v1/responses,
                             │        X-Hermes-Session-Key, Bearer per agent)
            ┌────────────────┼──────────────────┐
      [container user A] [container user B]  … [container user N]
      Hermes agent: skills, memory, playbook, cron — 24/7
            │                │
            └── MiniMax M2.7 API (our key; per-user budgets in Convex)
            └── Composio (per-user connected accounts: Google Calendar/Gmail/Notion)
```

## 3. Components

### 3.1 Agent image (the product's heart)
- Base: Hermes Agent (MIT, github.com/NousResearch/hermes-agent) Docker image,
  pruned (no browser stack by default, no CN platforms), pinned version.
- Provider: `minimax` (API key, Anthropic-compatible endpoint
  `https://api.minimax.io/anthropic`, model string `MiniMax-M2.7`). Auxiliary model
  slots → cheaper model for titles/compression. Fallback chain → Gemini Flash.
- **Saved-content skill** (ours, the core IP): triggers on any URL/media message:
  1. Resolve: IG → ScrapeCreators/Apify (primary) | yt-dlp+proxies (fallback);
     TikTok → yt-dlp; X → fxtwitter; YouTube → transcript-api/yt-dlp;
     articles → trafilatura/Jina. Runs via `terminal` tool inside the container.
  2. Understand: video file/frames + caption → MiniMax M2.7 (native video input);
     audio → whisper when speech matters. Output = **knowledge card**: суть,
     "how to apply to YOU" steps, category, entities, effort estimate.
  3. Store: card → agent memory + items.json in container volume; reply to user
     with card summary + one suggested next action.
  4. Schedule: resurfacing cron via Hermes `cronjob` tool — adapted
     memento-flashcards spaced cadence (1d → 3d → 7d → archive), with
     `wakeAgent` pre-checks and `[SILENT]` discipline (Dot lesson: earn every ping).
- **Playbook**: per-user style/preferences doc the background-review loop updates
  (Hermes' skill self-improvement, scoped naturally — it's the user's own container).
- **Draft-before-send** (ported pattern from Boop): a `pre_tool_call` plugin hook
  forces external actions (email, calendar writes, purchases) through a
  draft → user confirms in iMessage → commit flow.
- Hardening: toolset whitelist (no open shell beyond our pipeline scripts),
  url_safety/SSRF guard on the download path, cgroup CPU/mem limits,
  egress allowlist.

### 3.2 Router + Control plane (TS + Convex)
- Sendblue webhook receiver (verify signature/secret) → normalize → look up
  user by E.164 phone → POST to that user's container (Hermes API server,
  per-agent bearer token) → relay reply back through Sendblue. Typing
  indicators on; long replies chunked.
- Convex tables: `users` (uuid PK, phone E.164, plan, status, consent{ts,ip,text},
  container{host,port,token,version}, quotas), `usageEvents` (per-user tokens/$,
  itemized), `entitlements` (Paddle sub state), `fleetHosts`, `messageLog`
  (minimal metadata for dedup/rate-limit, not content), `provisionJobs`.
- Quota middleware: free tier = N items/mo + M agent-actions/mo (counters in
  Convex; soft-fail message offers upgrade link). Paid = higher caps.
- TCPA: STOP/UNSUBSCRIBE/etc. processed in the router (instant suppression,
  before any LLM), quiet hours per user timezone, consent recorded at signup.
- Proactive path: agent containers send outbound via the router
  (`POST /outbound` with agent token), router enforces suppression/quiet hours/
  rate caps → Sendblue.

### 3.3 Fleet orchestrator
- Provisioner (TS service or Convex action → small GCE-side daemon): on signup,
  `docker run` user container from the pinned image on the least-loaded VM,
  mount per-user volume, register in `fleetHosts`/`users`, health-check, send
  welcome message. Target: < 60 s button-to-hello.
- Fleet ops: staggered cron offsets per user (no 8:00 thundering herd),
  rolling image upgrades (drain → swap → health-check), nightly volume backups
  to GCS, per-container watchdog (restart on crash; Hermes gateway is
  supervised by s6 inside the image).
- Capacity assumption (TO VERIFY in Phase 0): idle Hermes gateway ≈ 250–500 MB
  RAM → 30–100 users per 32–64 GB VM.

### 3.4 Landing + checkout
- One-page site (Next.js or static + Convex): value demo, phone input,
  consent checkbox (PEWC: company name, msg rates, revocation), Paddle checkout
  (MoR — handles global sales tax), free-trial path without card.
- Post-checkout → provisioning → "text you in a minute" → agent says hello first.

### 3.5 Integrations
- Composio per-user connected accounts (Google Calendar, Gmail, Notion):
  auth links sent in iMessage chat (`connectedAccounts.link(userId, ...)` hosted
  flow). Apple-ecosystem actions (no Composio toolkits) → .ics files sent in chat.
- Composio scopes minimal; May-2026 breach noted → self-owned auth configs.

## 4. Hosting

- **Phase 0–1: GCP** (user has gcloud CLI + ~$300 trial credits): 1–2 GCE VMs
  (e2-highmem-4 class) running Docker; credits make infra ≈ $0 for ~90 days.
  Trial caveats: 90-day expiry, must upgrade to paid account for production
  (credits survive the upgrade), default vCPU quotas.
- **Later**: stay on GCP (paid) or migrate to Hetzner dedicated (3–5× cheaper
  RAM). Migration = move volumes + update fleet map — designed as a non-event
  (containers + volumes are host-agnostic).

## 5. Data flow (happy path)

1. User shares reel → Messages → service number.
2. Sendblue webhook → router: signature ✓, user ✓, quota ✓ → forward to
   container A.
3. Hermes (user A): URL detected → saved-content skill → download → M2.7 video
   analysis → knowledge card → memory + resurfacing cron created.
4. Reply: "Сохранил: рецепт пасты за 15 мин. Хочешь список покупок в субботу
   утром?" (suggestion, not action — actions go through drafts).
5. Saturday 9:00 (user tz, staggered): cron fires → wakeAgent pre-check →
   agent drafts shopping list → sends via router (quiet-hours ✓).

## 6. Error handling

- Download fails (IG block): fallback chain; if all fail → honest reply +
  card from caption/oEmbed metadata only; retry queue (3 attempts, backoff).
- Container down: router health-check → restart; inbound queued (Convex) and
  replayed; user sees delayed reply, never silence (router fallback text after
  60 s: "разбираюсь, отвечу чуть позже").
- LLM provider down: per-container fallback chain (M2.7 → Gemini Flash).
- Sendblue outage: incident banner skill — nothing we can do mid-outage;
  monitor + alert. (Long-term de-risk: Apple Messages for Business application.)
- Budget runaway: per-user daily token budget in router; hard stop + notify.

## 7. Security & compliance

- Threat #1: prompt injection via saved content (malicious caption) → agent has
  no shell beyond whitelisted pipeline scripts; external actions gated by
  draft-confirm; per-user container = blast radius of one.
- Webhook auth (Sendblue secret), per-agent bearer tokens, no cross-container
  network access (docker network isolation), egress allowlist.
- TCPA: PEWC at signup, STOP-class keywords honored in router instantly,
  quiet hours, suppression list, A2P 10DLC registration when SMS fallback added.
- Privacy: user content stays in their container volume + minimal metadata in
  Convex; no free-tier LLM endpoints in production (data-training leak);
  deletion = destroy container + volume + rows (one command).

## 8. Economics (verify constants in Phase 0)

Per paying user/mo: infra $0.3–1.5 (GCP credits → then real) + MiniMax ≈ $1.5–2.5
(caching helps: cached input $0.06/M) + Sendblue/Convex share ≈ $0.5
→ COGS ≈ $2.5–4.5 → 60–75% margin at $9–13. Fixed: Sendblue AI Agent $100/mo
(prod), Convex ~$25, Paddle 5%+$0.50/txn.

## 9. Phases

- **Phase 0 — Лаборатория (weekend):** stock Hermes on the user's Mac
  (BlueBubbles or CLI), MiniMax (OAuth or API key), build+iterate the
  saved-content skill on the user's real bookmarks. Exit criteria: 20 real saves
  processed; card quality subjectively "хочу пользоваться"; RAM/cost measured.
- **Phase 1 — Флот (≈3 weeks):** agent image, router+control plane, provisioner,
  Sendblue sandbox→prod, landing with manual invites. Exit: 10–20 friends live,
  D7 retention of saves-per-user, p95 button→hello < 60 s.
- **Phase 2 — Деньги (≈2 weeks):** Paddle, freemium quotas, TCPA full,
  public beta. Exit: first paying strangers.
- **Phase 3 — Масштаб (later):** Apple Messages for Business application,
  transactions via drafts + **user-funded fixed-amount virtual cards
  (AgentCard, agentcard.sh — MCP-plugin: user confirms draft → funds card for
  the exact amount via hosted Stripe checkout → agent pays; card balance = max
  possible loss; we never hold user funds)**, premium tier, host migration
  decision.

## 10. Testing

- Pipeline golden set: 20 real saved items (from user's screenshots: arXiv paper,
  Common Crawl thread, vibe-coding reels, CS153 carousel…) → snapshot cards,
  regression on every skill change.
- Router: unit (signature, quota, STOP, quiet hours) + integration against a
  fake Sendblue + a live container.
- Fleet: provision/deprovision e2e on a scratch VM; chaos: kill container
  mid-conversation → replay works.
- Live vendor test FIRST in Phase 1: share a real reel to a Sendblue sandbox
  number, inspect webhook payload (URL fidelity) — go/no-go for Sendblue vs Blooio.

## 11. Risks

| Risk | Mitigation |
|---|---|
| iMessage gray-zone (Apple bans the category) | Same risk as Poke/Martin; Messages for Business application in Phase 3; channel adapter is swappable (Telegram/WhatsApp/SMS) |
| Sendblue payload doesn't carry clean URL | Live test day 1 of Phase 1; Blooio as tested fallback |
| IG blocks downloads harder | Paid scraper APIs primary (ScrapeCreators/Apify), not our IPs |
| RAM-per-agent worse than assumed | Measured in Phase 0; worst case = fewer users/VM, price tier adjusts |
| Hermes upstream churn (very active repo) | Pin version; quarterly conscious upgrades; our code = skill+plugins (stable seams) |
| GCP credits expire | Designed-for migration; decision point ~day 75 |
| Proactive fatigue (Dot lesson) | wakeAgent prechecks, [SILENT], per-user feedback loop ("реже"/"больше такого"), hard caps |

## 12. Rejected alternatives (and why)

- **Boop as base** (TS, Sendblue+Convex+Composio wired, drafts ready): rejected
  because shared-process multi-tenancy kills the per-user self-improving agent —
  the product's soul. Boop patterns (drafts, dashboard ideas) are ported instead.
- **Shared Hermes gateway with tenancy hooks**: fights Hermes' single-tenant
  grain; cross-user skill contamination risk; rejected.
- **Hermes deep rewrite to Convex storage**: XL effort inside foreign core; only
  MemoryProvider seam is clean; rejected. Convex = control plane only.
- **VPS per user**: right instinct, wrong unit — container on shared VM is
  5–10× cheaper with identical isolation semantics.
- **Telegram/WhatsApp first**: user chose iMessage (US iPhone audience, Poke
  precedent). Adapter layer keeps them as future channels.
- **Free-tier LLM rotation in production**: ToS/ban/data-training risks;
  dev/dogfood only.
- **MiniMax Max-Hermes platform**: consumer-only, no embed API (verified).
