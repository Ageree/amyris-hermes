# Hermes Agent — Deep Dive Synthesis (2026-06-07)

12 agents total: 4 code-study + 8 docs-study (all 340 pages of website/docs).
Repo: github.com/NousResearch/hermes-agent, MIT, 186K★, commit-today active.
Local clone: $CLAUDE_JOB_DIR/tmp/hermes-agent.

## What Hermes IS
Single-operator, multi-agent personal assistant engine. Python core (82.9%),
one `AIAgent` drives every surface (CLI/gateway/API/batch). SQLite+FTS5 only
persistence. Registry pattern everywhere (tools/providers/plugins/adapters).

## Crown jewels (verified in code+docs)

### Self-improving skills (the user's favorite)
- Skill = dir with SKILL.md (agentskills.io) + references/templates/scripts.
- Auto-improvement: after every ~10 tool-iterations, background fork reviews the
  conversation with ONLY memory+skills tools and actively patches/creates skills
  (`agent/background_review.py`, `_SKILL_REVIEW_PROMPT` "most sessions produce at
  least one update"). Curator consolidates weekly-ish on idle (`agent/curator.py`).
- Guardrails: tar checkpoints+rollback, never deletes (archives), pinning,
  optional security scan. NO semantic versioning of content.
- Scope: per-profile (~/.hermes/skills), NOT per-end-user.
- TS port estimate: 2-4 weeks. Or consume via Hermes-as-service.

### Proactive engine economics (best-in-class patterns)
- cron: NL-created by agent itself (`cronjob` tool), `wakeAgent` pre-check gate
  ($0 polling — wake LLM only if state changed), `no_agent` script-only mode
  (zero-token deterministic reminders), `[SILENT]` suppression, delivery to any
  platform incl. BlueBubbles. Gateway ticks 60s.
- webhooks: `deliver_only` zero-LLM template pushes; HMAC; rate limits; idempotency.
- Cron sessions are FRESH (no memory) — prompts must be self-contained.

### Media understanding
- `video_analyze` tool (opt-in `video` toolset): captions, scene breakdowns,
  timestamps from URL or file path. `vision_analyze` for images w/ aux-model
  fallback. NO built-in downloader — yt-dlp via `terminal` tool (sandboxable).
- Relevant skills: media/youtube-content (transcript→summary), mlops-whisper (ASR),
  scrapling (stealth scraping, CF bypass), social-media-xurl (X official CLI;
  x_search via xAI even has image+video understanding of X media),
  productivity/memento-flashcards (SPACED REPETITION, adaptive intervals, YouTube
  quizzes — fork candidate for resurfacing cadence).
- macOS launchd PATH gotcha: ffmpeg/yt-dlp "not found" in gateway → re-run
  `hermes gateway install`.

### Providers / MiniMax
- MiniMax first-class: `minimax` (API key, default base https://api.minimax.io/anthropic
  — Anthropic-compatible), `minimax-cn`, `minimax-oauth` (consumer PKCE login,
  NO API key/card — dogfood-friendly; docs reference M2.7, M3 = pass model string).
- Credential pools (rotation on 429/402/401, strategies, cooldowns) + cross-provider
  fallback chains + 11 auxiliary model slots (route vision/compression/titles to
  cheap models). Always-on prompt caching.

### Embedding/integration seams
- `python-library`: `from run_agent import AIAgent`; `quiet_mode=True`,
  `skip_memory`, `ephemeral_system_prompt` per request (per-user persona!),
  one instance per thread.
- API server :8642: /v1/chat/completions, /v1/responses, Runs API (/v1/runs SSE +
  approvals), Jobs API (cron CRUD via REST), Sessions API.
  **X-Hermes-Session-Key header scopes long-term memory per channel/user.**
- GATEWAY_PROXY_URL: gateway = platform I/O only, agent work on remote API server
  (split deployment).
- Hooks: `pre_llm_call` (context injection = RAG seam), `pre_gateway_dispatch`
  (gating/rewrite = tenant routing/rate-limit seam), `transform_*`, shell hooks.
- MemoryProvider ABC: per-user Postgres memory provider is feasible (but ONE
  provider active per profile → route by user_id internally). Honcho = dialectic
  user modeling w/ per-peer isolation.
- Kanban: durable SQLite work queue, named-profile OS-process workers, 60s
  dispatcher, retry/circuit-breaker, `--tenant` scoping + HERMES_KANBAN_* env
  isolation. The durable background-work primitive (delegate_task is synchronous,
  dies with the turn).

### iMessage reality
- BlueBubbles adapter mature (1038 L, webhooks in, REST out, media both ways,
  pairing/allowlist/open auth modes, group mention-gating, tapbacks/typing need
  Private API helper). **One Mac = one Apple ID = one iMessage identity** — not a
  service-number model. apple/imessage skill (imsg CLI) as lighter macOS alt.
- NO Sendblue/Blooio adapter in-tree. Closest template: sms.md/Twilio adapter
  (379 L: webhook-in + HMAC verify + REST-out + E.164 allowlist + home channel).
  Estimated ~350-450 LOC as a registry plugin, few days incl. media+delivery status.
- Proactive outbound: YES everywhere (home channel + send_message tool + cron +
  deliver_only webhooks).

## Multi-tenancy — the hard NO (consistent across code+docs)
- Session isolation per chat_id: YES (separate transcripts per phone number).
- Data/identity isolation: NO. One process, one FS, one ~/.hermes, one credential
  set, memory/skills/SOUL.md profile-global. sessions.user_id = unenforced tag.
- Profiles = process-per-tenant (own HERMES_HOME, s6/systemd service each, token
  conflict locks; "never point two gateways at one data dir"). Scales to TENS,
  not thousands. SECURITY.md self-declares single-tenant (§2.2).
- No accounts/quotas/billing primitives anywhere. Auth = operator
  allowlist/DM-pairing (friend-gating, not customer accounts).
- Concurrency ceiling: single asyncio loop + default ThreadPoolExecutor
  (min(32, cpu+4)) + agent cache 128 → ~30 concurrent turns max.
- No draft-before-send for external actions (approval gate is shell-command-centric).

## Implications for product design
- Per-user self-improving skills à la Hermes = per-user mutable installation.
  At SaaS scale rethink as: GLOBAL product skill library (improved from aggregate
  feedback) + per-user memory/preferences (Honcho pattern / Convex tables).
- For PERSONAL dogfood Hermes is ~zero-code TODAY: install on Mac + BlueBubbles +
  minimax-oauth + write "saved-content" skill (yt-dlp + video_analyze + cron
  resurfacing modeled on memento-flashcards). Days, mostly markdown.
- For PRODUCT: tenancy/billing/quotas must be built regardless; Boop's TS/Convex
  base remains the shorter path (multi-tenancy = L vs Hermes XL), with Hermes
  patterns ported: approval/draft gate, url_safety SSRF, wakeAgent/no_agent cron
  economics, [SILENT], skill format, memento resurfacing cadence, pairing-code
  onboarding, deliver_only pushes.

## Options on the table
- D1: Boop-base product + port Hermes patterns (original recommendation).
- D2: Hermes-base everything (fast dogfood; product fights single-tenant grain).
- D3 (NEW recommendation): Phase 0 dogfood on stock Hermes (this weekend, zero
  code, MiniMax OAuth free) → validate resurfacing value on own saves → Phase 1
  product on Boop-base TS multi-tenant, porting validated patterns.
- D4: thin TS tenancy layer + Hermes farm via API server (X-Hermes-Session-Key):
  viable mid-path but per-user skills still profile-bound; ops-heavy.
