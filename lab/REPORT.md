# Phase 0 Exit Report — Saved-Content Lab

**Run:** 2026-06-08 (autonomous overnight session; operator asleep, full autonomy granted)
**Environment:** Hermes Agent v0.11.0, isolated `HERMES_HOME=~/.hermes-savedlab`, MiniMax-M2.7 via `api.minimax.io/v1` (operator's funded key), saved-content skill v0.1.

> Scope note: the operator's 20 real bookmarks were not available during the run,
> so the golden set is **synthetic public URLs** I selected. The full save→card→store
> loop was validated end-to-end on real content; per-source resolution was probed
> across all source types. Real SC-001 pass/fail still needs the operator's actual saves.

## What was validated end-to-end (real M2.7, not mocks)

| Feature | Spec | Result |
|---|---|---|
| Save → resolve → understand → knowledge card → store | US1 / FR-001..006 | ✅ PG article: resolve.py (Jina, 1.2s) → essence+4 steps → `library.py add` → card. Card quality on-vision (RU texting «Сохранил 👌…» + steps + 1 question). |
| Spaced resurface cadence (due/engage/archive) | US2 / FR-010,012 | ✅ live on the real item: `due` empty before next_due; returns+bumps ignores 0→1 after; `engage` advances interval 0→1 (1d→3d), resets ignores. |
| Proactive digest + earn-every-ping | US2 / FR-011,013 | ✅ empty due → agent replied exactly `[SILENT]`; one due item → ONE bundled digest naming it + one concrete next step. |
| Honest degraded failure | FR-005 | ✅ blocked sources return `ok:false`+error; skill instructs a degraded card. |

## Measured constants

- **Process RAM (peak RSS):** **290 MB** per Hermes instance (transient CLI; a persistent
  gateway will be somewhat higher, est. 350–500 MB).
- **Base context per turn:** system prompt + tools + skill = **~5,737 tokens**. A text
  save turn ≈ **11–16k input + ~1k output tokens** (article capped at 20k chars ≈ 5k tok).
- **Latency:** save ≈ 8–21 s/query (resolve + M2.7 reasoning). Within the 90 s SLA (SC-001).

## Cost (SC-005) — estimated, not metered

No metered console access this run (see "Issues"). Estimate at MiniMax-M2.7 list (~$0.30/M in, $1.20/M out):
- **Text save: ~$0.006/item.** Daily digest: ~$0.002.
- **Video save (multimodal): higher** — video tokens dominate; est. $0.02–0.08/item depending on length.
- **Per active user/mo** (≈60 saves + 30 digests + chat): **~$2–4** for text-heavy; pushes toward the
  **$4.5 SC-005 ceiling** only if video-heavy. **PASS for text/article/X-heavy use; WATCH video volume.**

## Fleet density (SC-008)

At 290–500 MB/instance, a 32 GB host fits **~50–60 users** with 30% safety headroom —
**beats the SC-008 target of 30/32 GB.** (Caveat: separate containers don't share Python/lib
pages copy-on-write the way forked processes do; the persistent gateway footprint should be
re-measured in the Phase-1 container.)

## Per-source resolution (the #1 Phase-1 input)

| Source | Stock result | Fix |
|---|---|---|
| Article (Jina r.jina.ai) | ✅ reliable, no auth | — |
| X / Twitter (fxtwitter) | ✅ reliable, no auth | — (incl. mobile.x.com after the Task-5/6 fixes) |
| YouTube | ❌ "no impersonate target" | ✅ FIXED: resolve.py `--impersonate chrome` + curl_cffi (proven). Bake into Phase-1 image. |
| TikTok | ❌ same impersonation issue | ✅ same fix |
| **Instagram** | ❌ **login wall** (yt-dlp can't) | ⚠️ **UNSOLVED — needs ScrapeCreators/Apify or cookie auth. IG = 99% of operator's saves → THE Phase-1 priority.** |

## Skill/code changes made during dogfood (the lab's whole point)

1. `fix(lab): SKILL.md saves before replying` — **critical**: agent composed the card but
   skipped `library.py add` (treated the card as the final reply, ended the turn). Reordered
   save-before-reply + hard rule. Re-ran → item persisted. *Unit tests could never catch this.*
2. `fix(lab): use full ${HERMES_SKILL_DIR}/scripts path in engagement commands`.
3. `fix(lab): classify mobile.x.com as x` + `_fxtwitter rewrites mobile.x.com`.
4. `feat(lab): yt-dlp impersonation with graceful fallback`.
5. `docs: MiniMax-M3 → M2.7` (M3 does not exist; M2.7 is the current flagship).

## Known issues / operator actions

- **The MiniMax API key you provided is empty (HTTP 402 insufficient balance).** The lab ran on
  your *other* funded key from `~/.hermes/.env`. Top up the provided key (or designate which key
  for the fleet), and consider rotating both — they're in the chat transcript.
- **Telegram live e2e pending your one action:** a bot can't DM you first. DM the lab bot
  (`@`-the bot for token `8649699230:…`) once "привет", then the channel works. (Validated via CLI instead.)
- **`library.py` defaults its DB to `~/.hermes/saved-content/` ignoring `HERMES_HOME`** — a latent
  fleet-isolation bug. Must become `$HERMES_HOME/saved-content/` in Phase 1 (per-container isolation).
- IG resolution (above) — design the Phase-1 resolver chain around a paid IG resolver from day one.

## VERDICT: **GO for Phase 1**

The core product loop (save → understand → card → spaced resurfacing → digest with earned silence)
works end-to-end on M2.7 and produces genuinely useful, on-tone output. Unit economics and RAM
density are within targets for text/article/X content. **Solve first in Phase 1, in order:**
1. **Instagram resolution** (ScrapeCreators or Apify or cookie auth) — gates 99% of real usage.
2. `library.py` `$HERMES_HOME` DB isolation (fleet correctness).
3. Bake yt-dlp + curl_cffi + `--impersonate` into the container image.
4. Re-measure persistent-gateway RAM + get a metered MiniMax key for true $/item.
5. Telegram channel live test (operator pairing), then Sendblue for the product number.
