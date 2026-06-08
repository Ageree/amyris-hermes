# Atoms: Poke-style iMessage assistant for saved social content

Product: user shares saved content (IG reels/carousels, X threads, TikTok, articles,
screenshots) to an iMessage number → assistant understands it, resurfaces it with
reminders, and executes agentic actions (summaries+plans, calendar/reminders,
research errands; transactions later). Freemium (Poke-style: most free, paid lifts
limits, ~$9-13/mo), iPhone-first, non-technical users.
Base model: MiniMax M3 (model-agnostic architecture). Tools: Composio.

## Atomic capabilities

| # | Atom | Description |
|---|------|-------------|
| 1 | iMessage channel | Send/receive iMessage as a service: bridge (Blooio/Sendblue/BlueBubbles), receive shared URLs from iOS share sheet, proactive outbound |
| 2 | Content resolution | URL → video/images/caption/thread (IG, TikTok, X, YouTube, articles); downloaders, scraper APIs |
| 3 | Multimodal understanding | Video+frames+ASR / carousels / articles → structured "knowledge card" (summary, action plan, category) |
| 4 | Memory & library | Per-user store of items, embeddings/search, user profile & preferences |
| 5 | Proactive engine | Spaced resurfacing, digests, nudges; trigger table + scan loop |
| 6 | Agentic execution | Research errands, calendar/reminders via Composio; HITL approval before real actions |
| 7 | Personality/chat layer | Poke-style short texting, multi-message bursts, user memory |
| 8 | Billing & limits | Freemium metering in Postgres, Paddle payment links from iMessage |
| 9 | LLM routing & cost | MiniMax M3 base via OpenAI-compatible endpoint; Gemini Flash fallback for video; per-user budgets |
| 10 | Onboarding | Landing page → text the number; OTP-verified phone (E.164) + internal UUID |

## Wave status

- Wave 1 (done 2026-06-07): Poke, Martin, OpenClaw, Karakeep, resurfacing apps + Dot post-mortem
- Wave 2 (done 2026-06-07): iMessage bridges, downloaders, MiniMax M3 verification,
  Composio+frameworks, backend/scheduling, LLM routing/free tiers, billing, proactive patterns
- Waves 3-5: after design approval, before implementation plan
