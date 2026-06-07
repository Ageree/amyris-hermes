# Golden Set Ratings — run 2026-06-08 (autonomous overnight, synthetic public set)

Scoring: useful 2 = «хочу пользоваться», 1 = норм, 0 = мимо.
Pass (SC-001 lab edition): ≥18/20 resolved or honest-degraded, ≥15/20 useful≥1.

| n | url | resolved? | card in ≤90s? | useful (0-2) | notes |
|---|-----|-----------|---------------|--------------|-------|
| 1 | paulgraham.com/ds.html | yes | yes (~21s) | 2 | full e2e: essence+4 steps+1 Q, RU texting tone, on-vision |
| 2 | blog.samaltman.com/how-to-be-successful | yes (resolve) | n/a | — | Jina 20k chars; not run through LLM (probe only) |
| 3 | x.com/naval/...1002103360646823936 | yes (resolve) | n/a | — | fxtwitter text ok |
| 4 | youtube.com/watch?v=dQw4w9WgXcQ | partial | n/a | — | needs --impersonate+curl_cffi (works in lab venv; brew lacks) |
| 5 | instagram.com/reel/C8XbOLZyhqz/ | no | n/a | — | login required — honest failure; needs paid resolver |
| 6 | tiktok.com/@khaby.lame/...7137723462233444613 | partial | n/a | — | impersonation backend needed (same fix as YT) |

## Summary (synthetic set, not the real SC-001 gate)
- **Full LLM e2e**: 1 item (PG article) — save→understand→card→store, card quality 2/2.
- **Resolve reliability by source** (the key Phase-1 input):
  - article (Jina): 2/2 OK, no auth, fast.
  - x (fxtwitter): 1/1 OK, no auth.
  - youtube/tiktok: FAIL on stock brew yt-dlp → FIXED in resolve.py with graceful
    `--impersonate chrome` (proven retrieving YouTube in a curl_cffi-enabled venv).
  - instagram: FAIL (login wall) — UNFIXED by yt-dlp; needs ScrapeCreators/Apify or
    cookie auth. **This is the #1 Phase-1 cost/feature driver — IG is 99% of saves.**
- This synthetic run validates the PIPELINE. The real SC-001 pass/fail needs the
  operator's 20 actual bookmarks (esp. real IG reels/carousels behind login).
