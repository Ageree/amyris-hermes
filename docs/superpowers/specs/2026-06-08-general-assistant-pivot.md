# Design Delta: General-Purpose Assistant + Real Browser (pivot)

Date: 2026-06-08 · Status: **proposal — awaiting operator review** · Supersedes framing (not architecture) of `2026-06-07-saved-content-agent-design.md`

> This is a **delta**, not a rewrite. The locked "Hermes Fleet" architecture (Sendblue → router/Convex control plane → per-user Hermes container → MiniMax-M3) **stays**. What changes is the *product framing* and which capability is the foundation. Operator decision (2026-06-08): _"я решил делать личного ассистента общего назначения; способность анализировать рилсы и тик токи сама появится как только дам агенту реальный браузер, чтобы тот мог делать действия на сайтах."_

## 1. What changes

| | Before (saved-content tool) | After (general-purpose assistant) |
|---|---|---|
| **Product** | Niche: save IG/TikTok/X → cards + resurfacing | Poke-style **general personal assistant** in iMessage; saved-content is **one skill** among many (calendar, email, research, web errands, reminders) |
| **Core capability** | URL→media resolvers (yt-dlp / fxtwitter / Jina) + paid IG resolver | **A real, per-user logged-in browser** — the agent *does actions on websites*. Reel/TikTok understanding is a **downstream emergent capability** of that browser, not a separate resolver problem |
| **Instagram** | DECIDE-1: pay ScrapeCreators/Apify per resolve (login wall) | **Logged-in browser reaches the content natively.** Per-resolve API fee → mostly gone; replaced by browser compute |
| **Model** | (briefly mis-"corrected" to M2.7) | **MiniMax-M3** — frontier multimodal, 1M ctx, native video-in. Confirmed live (HTTP 200). Re-validated e2e on the core loop 2026-06-08 |

## 2. Key finding — the browser is already built into Hermes

We do **not** build a browser from scratch (frankenstein principle: 5% glue, 95% library). Hermes Agent v0.11.0 ships a complete, production-grade browser toolset:

- **Tools the agent gets:** `browser_navigate`, `browser_snapshot` (accessibility tree with `@e1` ref IDs — LLM-native, not pixels), `browser_click`, `browser_type`, `browser_scroll`, `browser_press`, `browser_back`, `browser_get_images`, **`browser_vision`** (screenshot + vision-AI — the agent can *watch* a reel frame, not just read text), `browser_console`, `browser_cdp` (raw Chrome DevTools escape hatch), `browser_dialog`.
- **Providers (pick per environment):** Browserbase (cloud, residential proxies + CAPTCHA solving + stealth — best anti-bot), Browser Use (cloud), Firecrawl (cloud+scrape), **Camofox** (local Firefox anti-detection with **persistent per-user profiles**), local Chrome via CDP, and pure-local `agent-browser`+Chromium (free).
- **Persistent per-user logged-in sessions:** Camofox `managed_persistence` scopes a stable `userId` to the active **Hermes profile** → cookies/logins survive restarts, and **profiles are isolated per Hermes profile**. This maps 1:1 onto the fleet model: one `HERMES_HOME` per user = one isolated, persistent, logged-in browser profile. **This is what defeats the Instagram login wall** that yt-dlp could not.

### Validated live (2026-06-08, MiniMax-M3, local mode, free)
- `browser_navigate https://example.com` (5.8s) → accessibility-tree snapshot → agent extracted H1 **"Example Domain"** correctly, in 26s total. 28 tools active, browser included in the default `hermes-cli` preset. **The agent has a real browser today.**

## 3. What stays (unchanged from locked design)
- Hermes Fleet: one Sendblue number → router + Convex control plane → per-user Hermes container on GCP → MiniMax-M3.
- Sendblue is the iMessage channel (**DECIDE-2 resolved**; shared number created, API keys live-verified 2026-06-08).
- Per-user isolation via `HERMES_HOME` (already fixed in `library.py`); the same boundary now also isolates each user's browser profile.
- Saved-content skill, spaced resurfacing, digest discipline — all retained as **one** of the assistant's skills.
- Convex = control plane only (users, billing, quotas, TCPA, fleet map). Composio for connected accounts.

## 4. How reel/TikTok understanding "emerges" (the operator's thesis, concretely)
1. User shares a reel → agent's saved-content skill triggers.
2. **Resolve via browser, logged-in:** `browser_navigate` to the reel in the user's persistent IG session → past the login wall.
3. **Understand, two composable paths:**
   - `browser_vision` screenshots key frames → M3 multimodal reads them; and/or
   - now authenticated, the agent extracts the media URL / triggers a download → feeds the video to **M3 native video-in**.
4. Knowledge card → store → resurface. Same downstream loop, but the *access* problem is solved by the browser instead of a paid API.

This is why no separate IG-resolver vendor is needed for the common case. (Keep yt-dlp/fxtwitter/Jina as the cheap fast path for public, no-login content — browser is the heavier fallback that also unlocks *actions*.)

## 5. Decisions for the operator (genuinely yours)
- **D-A — Fleet browser provider.** Recommendation: **Camofox (self-hosted) for per-user persistent logged-in sessions**, because the product needs durable per-user IG/TikTok/X logins, and Camofox's userId-per-profile model fits the fleet exactly. Use **Browserbase as a paid fallback** for sites with aggressive anti-bot where Camofox gets blocked. (Pure-local `agent-browser` is fine for the lab; not for the fleet's logged-in needs.)
- **D-B — Instagram login.** To prove the logged-in-reel e2e end to end, the agent needs *a* logged-in IG session. For the lab: do you want to (i) provide a throwaway IG account's login for me to test the browser resolving a real reel, or (ii) keep the lab on public content and defer logged-in IG to the fleet? (No silent action — I won't log into any account without your go-ahead.)
- **D-C — Scope of "general-purpose" for the first beta.** Recommendation: ship the assistant with **browser + calendar/email (Composio) + saved-content** as the v1 skill set, rather than trying to be everything. Confirm or redirect.

## 6. Immediate next steps (autonomous, pending your nod on §5)
1. Enable the `browser` toolset explicitly in the fleet container image (`platform_toolsets` / preset), layered on the Phase-0 `resolver-core` image.
2. Add a Camofox sidecar to the container plan; wire `managed_persistence` + per-user `HERMES_HOME` profile.
3. Rework Phase-1 plan: demote DECIDE-1 (paid IG resolver) → browser-first resolution; add a "browser actions" milestone; keep Sendblue webhook round-trip as the first live gate.
4. (If D-B = provide login) e2e: agent resolves a real IG reel logged-in + `browser_vision` understanding on M3.
