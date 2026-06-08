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

## 2.1 Browser stack — operator's three tools, two lanes (decided 2026-06-08)

Operator chose **Camofox + Browserbase + `browser-use/browser-harness`** (MIT, 14.5k★). These do NOT all compose on one backend — two verified constraints drive the design:

- **browser-harness is Chrome/CDP-only** (`BU_CDP_URL=http://127.0.0.1:9222`; Chrome launched `--remote-debugging-port=9222 --user-data-dir=<isolated>`; `chrome://inspect` per-attach approval on Chrome 144+). **Camofox is Firefox (Camoufox)** — Firefox only ships a partial, Mozilla-deprecated CDP subset → **browser-harness cannot reliably drive Camofox.** It pairs with Browserbase (Chrome cloud, per-session CDP) or a local Chrome.
- **browser-harness has no own LLM loop** — it's driven by an external coding agent ("paste into Claude Code/Codex"). In the fleet, **Hermes is that driver** (its `python`/`terminal` tool runs the harness CLI: `browser-harness <<'PY' … PY`, `browser-harness --doctor`). Its **self-healing domain-skills** (`agent-workspace/domain-skills/<site>/`, set `BH_DOMAIN_SKILLS=1`) accumulate per user → the "self-improving skills" property, applied to browser actions.

| Lane | Backend | Driver | Use for |
|---|---|---|---|
| **A — "log in once" persistent sessions** | **Camofox** (Firefox, anti-detect, per-user persistent profile via `managed_persistence`) | Hermes built-in `browser_*` tools | Acting *as the logged-in user* (IG, X…). One-time login via Camofox VNC live-view → cookies persist per `HERMES_HOME`. Cheap, always-on. **This is the operator's "user logs in once, agent acts inside Insta" model.** |
| **B — hard targets + self-healing automation** | **Browserbase** (Chrome/CDP; residential proxies, CAPTCHA, persistent Contexts) | **browser-harness**, driven by Hermes | Aggressive-anti-bot sites, complex multi-step web tasks; per-site domain-skills improve every run. |

**To verify before locking (do NOT assume):** (i) whether browser-harness accepts a *remote* Browserbase CDP URL (docs show only local `127.0.0.1:9222`) or needs a local Chrome that itself bridges to Browserbase; (ii) the Hermes→browser-harness driver integration (Hermes shells the harness CLI). De-risk by prototyping browser-harness against a local Chrome first.

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

## 5. Decisions — status 2026-06-08
- **D-A — Browser stack. RESOLVED:** Camofox + Browserbase + `browser-use/browser-harness`, organized as the two lanes in §2.1.
- **D-B — Instagram / logins. RESOLVED (model, not vendor):** operator — _«пока пофиг на инстаграм, надо будет просто сделать чтобы пользователь смог один раз залогиниться и думаю агент сможет совершать действия внутри инсты»_. So: **one-time user login → agent acts inside the persistent session** (Lane A / Camofox + VNC live-view). No throwaway account needed now; logged-in-reel e2e deferred until the one-time-login UX exists. IG is not a priority target — the general capability is.
- **D-C — Composio. RESOLVED → installed per `composio.dev/hermes`:** operator provided an `ak_` account key and said install it. Done: MCP server `composio` (HTTP, `https://connect.composio.dev/mcp`, `auth: oauth`, **no headers — per the guide's explicit instruction**) registered in `~/.hermes-savedlab/config.yaml`; `hermes mcp list` shows it. `ak_` key stored in lab `.env` as `COMPOSIO_API_KEY` (for SDK/dashboard/connected-account management — NOT the MCP header; the gateway rejects the raw key, wants an AuthKit JWT). **Connection state = "failed" pending a one-time OAuth (AuthKit) authorization** — operator runs `hermes mcp login composio` once (interactive browser). This mirrors the Lane-A "log in once" model. v1 skill scope = browser + saved-content + Composio connectors (Calendar/Gmail/Notion/…).

## 6. Immediate next steps
1. **De-risk Lane B:** prototype `browser-harness` against a local Chrome (`uv tool install -e .`; `--remote-debugging-port=9222`; `browser-harness --doctor`; a `page_info()` smoke). Confirm (i) remote/Browserbase CDP support and (ii) Hermes-as-driver (shell the harness CLI from Hermes' `python`/`terminal` tool).
2. **Lane A one-time-login UX:** stand up Camofox with `managed_persistence`, wire per-user `HERMES_HOME` profile, and design the VNC live-view handoff so the user logs in once.
3. Enable the `browser` toolset explicitly in the fleet container image, layered on the Phase-0 `resolver-core` image; add a Camofox sidecar to the container plan.
4. Rework the Phase-1 plan: demote DECIDE-1 (paid IG resolver) → browser-first resolution; add a "browser actions (two lanes)" milestone; keep the Sendblue webhook round-trip as the first live gate.
5. Defer: Composio connectors (D-C), logged-in-reel e2e (until step 2's UX exists).
