# Wave 1-2 Research Findings (2026-06-07)

Condensed synthesis of 12 parallel research agents. Source URLs in agent reports were
verified by WebSearch/WebFetch at research time.

## Competitive landscape (Wave 1)

### Poke (poke.com, Interaction Co) — primary reference
- ~$25M raised, ~100M messages relayed; public launch Mar 2026.
- Built on **Linq API** (comms infra). Number +1-650-422-9093. **First AI agent approved
  on Apple Messages for Business (Jun 4, 2026)** — per-conversation anonymized IDs.
- Features: email triage, calendar, reminders, morning briefings, meeting prep,
  integrations via MCP + shareable text "recipes". Highly proactive (8am digest +
  event-triggered nudges; ~70% useful per reviewers).
- Pricing: freemium, price *negotiated* with "Bouncer" persona ($0–75/mo observed,
  ~$9.99 typical). Most non-realtime features free.
- Personality: sassy, multi-message texting bursts, "friend, assistant, or nemesis".
- Complaints: opaque pricing, aggressive Bouncer, privacy concerns.
- **OpenPoke**: open-source clone by Composio — study its architecture.

### Martin (trymartin.com, YC S23)
- $21–49/mo, 7-day trial. Dedicated number per user (bridge undisclosed).
- Calendar/email/reminders/research/calls-texts on behalf.
- **No saved-social-content feature — our gap is real.**
- Complaints: broken calling features, sign-in failures, price vs value.

### OpenClaw (MIT, 377K★) — pattern source, not foundation
- 20+ channels; iMessage via bundled `imsg` CLI on a signed-in Mac (JSON-RPC/stdio).
- Model-agnostic incl. MiniMax M2/M3. Memory: JSONL/Markdown.
- **Single-operator by design; multi-tenancy on roadmap only. Severe prompt-injection
  findings (91.3% injection success per ZeroLeaks).** Use patterns (gateway/agent split,
  channel adapters), not the codebase.

### Karakeep (AGPL — pattern-copy only)
- Stack to imitate: playwright+stealth crawler, @mozilla/readability + metascraper,
  yt-dlp via execa (videoWorker), liteque (SQLite queue), drizzle, OpenAI-compatible
  inference indirection (OPENAI_BASE_URL).
- **No reminders/resurfacing (issue #705, most-requested) — our differentiator.**
- IG/TikTok ingestion pain: login walls, cookie banners, proxy needs (#414, #1863).

### Resurfacing mechanics + Dot post-mortem
- **Readwise daily digest = gold standard**: probabilistic spaced repetition
  (half-lives 7/14/28d), 5–15 items/day push. mymind = passive "Serendipity" (doesn't
  chase you → graveyard persists). MyMemo = daily 3-min audio podcast (novel hook).
- **Dot (New Computer) shut down Oct 2025**: weak proactive suggestions trained users
  to ignore the channel; tiny traction; GPU economics. Lesson: **earn every
  interruption — few, high-relevance pings; never volume.**
- Poke data point: ~2 useful pings/day max; segment by activity (active users ~4/week
  tolerance for marketing-grade pushes; 23.5h-after-last-session Duolingo timing).

## Technical stack (Wave 2)

### iMessage bridges (all blue-bubble = gray-market Mac farms; ToS risk priced in)
| Option | Price | Notes |
|--------|-------|-------|
| **Blooio** | $39 shared / ~$98 dedicated, flat | Only one exposing link-preview metadata in webhook; signed webhooks |
| **Sendblue** | $100/mo inbound line; outbound lines $1000+/mo | Best docs/API, SOC2, RCS→SMS fallback |
| LoopMessage | $60–100 + add-ons | Proactive init = +$30/mo add-on |
| BlueBubbles (self-host Mac) | free | Raw chat.db access (best fidelity), ~100 msg/day safe ceiling, you own Apple-ID ban risk |
| Apple Messages for Business | approval-gated | Sanctioned (Poke got in!) but customer-initiated; no cold outbound. Target for scale phase |
- Shared IG reel arrives as **URL balloon** (com.apple.messages.URLBalloonProvider):
  raw URL recoverable; **live test per vendor mandatory** before committing.

### Content resolution chains (primary → fallback)
- **Instagram** (hardest; DC IPs insta-blocked): ScrapeCreators (~$1.90/1k) or Apify
  ($1.00–1.50/1k) → self-hosted yt-dlp+instaloader behind residential proxies.
- **TikTok**: yt-dlp (no cookies needed) → cobalt self-host → ScrapeCreators.
- **X/Twitter**: fxtwitter API (free, self-hostable) → syndication API → Apify.
  Official API: $0.005/read, unusable.
- **YouTube**: youtube-transcript-api → yt-dlp --write-auto-subs (+ residential proxies at volume).
- **Articles**: trafilatura or Jina Reader (r.jina.ai) → Firecrawl for JS-heavy.
- Karakeep/cobalt internals confirm: monolith+readability+yt-dlp pattern works.

### Models — VERIFIED facts
- **MiniMax M3** (launched Jun 1, 2026): natively multimodal **text+image+VIDEO input**
  (no audio in), 1M context, OpenAI-compatible endpoint api.minimax.io/v1,
  $0.60/$2.40 per M (promo $0.30/$1.20 to ~Jun 8), cached input $0.06/M.
  SWE-Bench Pro 59.0, Terminal-Bench 2.1 66.0 (vendor-reported). ~100 tok/s.
- **Max-Hermes / MiniMax Agent**: consumer products, NO embeddable API → build agent
  loop ourselves on M3 API.
- **Video fallback**: Gemini Flash video API ~263 tok/s default res → <1¢ per 60s reel.
- ASR: Whisper/faster-whisper (MiniMax has no ASR).

### Agent layer
- **Vercel AI SDK 6**: recommended. Built-in tool-approval HITL (pause/approve/deny),
  MiniMax community provider + AI Gateway minimax/minimax-m3. Mastra = alternative
  (suspend/resume, memory, evals). LangGraph = heavier.
- **Composio**: hosted auth Connect Links (`connectedAccounts.link()` — NOT deprecated
  `initiate()`); free 20k calls/mo, $29/mo 200k. Has Google Calendar/Gmail/Notion.
  **No Apple/iCloud toolkits.** May 2026 breach (0.3% connections) — minimize scopes,
  consider self-owned auth configs. Apple-ecosystem actions via .ics files in iMessage.

### Backend
- **Constraint: yt-dlp/ffmpeg need real binaries** → Convex actions/CF Workers/Supabase
  Edge can't run them. Container worker mandatory OR Trigger.dev (bundles ffmpeg via
  build extensions, no timeout).
- Recommended: **Supabase (Postgres+pgvector) + Trigger.dev** (single job system incl.
  binaries, cron, wait.until for LLM-scheduled follow-ups) — or Inngest + Fly/Railway
  container. ~$75/mo at 100 users, ~$250–350 at 5k.
- Proactive engine: **Poke's actual pattern (per OpenPoke): SQL trigger table + 1-min
  scan loop; agent creates its own triggers** ("remind me when..."). Avoid cron-per-user.

### Economics
- Per active user/month (60 items + 120 chat turns + 20 agent runs ≈ 3.16M in / 216k out):
  M3 std **$2.41**, GPT-5-mini $1.22, Gemini Flash $1.49; with caching → ~$1–1.5.
- **$9–13/mo sub = 80%+ gross margin. Viable.**
- **Free-tier rotation: dev/prototyping only.** OpenRouter limits are global per-user
  (key rotation useless); Mistral free trains on data; proxy pools (zukijourney) violate
  upstream ToS. Production = paid APIs + per-user budgets (LiteLLM when needed).

### Billing & identity
- **Paddle** (MoR, flat 5%+$0.50) — payment link in iMessage → Apple Pay; customer
  portal link for self-service. No Apple commission risk (no app).
- Freemium counters: in-house Postgres (OpenMeter/Lago overkill <5k users).
- Identity: internal UUID PK + phone E.164 (libphonenumber) verified via OTP;
  re-verify on dormancy (number recycling: ~35M/yr US).

### Compliance (TCPA — landmine)
- Prior Express Written Consent at signup (checkbox, company name, msg rates, revocation).
- Honor STOP/QUIT/END/CANCEL/UNSUBSCRIBE/REVOKE instantly; suppression list; quiet hours.
- A2P 10DLC registration required for any SMS fallback (unregistered = 100% blocked).
- Apple Messages for Business has own opt-in gate (alternative path, Poke precedent).
