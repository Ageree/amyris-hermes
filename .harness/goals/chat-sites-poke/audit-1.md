# Audit 1 — chat-sites "works like Poke"

Re-verified from scratch (2026-06-23). The dispatched isolated subagent stalled
babysitting its own ~10-min battery and died after 1 build, so the long battery was
re-run at the Lead level via `Bash run_in_background` (harness-tracked, robust), the
deterministic gates were re-run inline, and the subjective quality scoring (AC4) was
delegated to 6 fresh independent judge agents to preserve independence.

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| AC1 | Build requests → heavy lane; chat does not | PASS | `test_fast_lane_build_routing.py` → `OK: 12 build / 8 chat routed correctly`, exit 0 |
| AC2 | Static build-in-turn: deploy + clean reply | PASS | 4/4 static probes ok: korica-bakery 59.4s/8615B, artyom-portfolio 66.6s/8098B, kai-music 41.4s/5872B, briz-cafe 72.0s/8626B — all built_in_turn, clean, HTTP 200, bytes ≥ 5872 (≥2000) |
| AC3 | App build-in-turn: Turso + data round-trip | PASS | 2/2 app probes ok: party-guestbook (62.5s, tabs=2, rt=true), cats-vs-dogs (89.5s, tabs=1, rt=true). CREATE/INSERT/SELECT/DROP on each app's own Turso DB via /site-data/<handle> succeeded; judges confirmed `dbQuery` INSERT+SELECT wiring |
| AC4 | Output genuinely good ("like Poke") | PASS | 6 independent judge agents, all SCORE=5/5 MOBILE=yes REAL_CONTENT=yes BROKEN=no → avg 5.00/5; every static ≥4 (all 5) |
| AC5 | Reliable across a battery, two passes | PASS | This fresh pass 6/6 ok, 0 chrome leaks, 0 interrogation-only (all built_in_turn). Prior recorded passes battery1 6/6 + battery2 6/6 corroborate → 3 independent green passes (18/18 real builds) |
| AC6 | No regression | PASS | `pytest` (4 acceptance files) → 33 passed, 0 failed, exit 0; `launchctl … com.savedcontent.worker` → PID 74673, last exit 0 (alive) |

## This-pass battery (Lead-run, independent)
| id | kind | ok | inturn | 200 | clean | bytes | rt | tabs | elapsed | url |
|----|------|----|--------|-----|-------|-------|----|------|---------|-----|
| s1 | static | ✓ | ✓ | ✓ | ✓ | 8615 | — | — | 59.4s | /s/korica-bakery |
| s2 | static | ✓ | ✓ | ✓ | ✓ | 8098 | — | — | 66.6s | /s/artyom-portfolio |
| s3 | static | ✓ | ✓ | ✓ | ✓ | 5872 | — | — | 41.4s | /s/kai-music |
| s4 | static | ✓ | ✓ | ✓ | ✓ | 8626 | — | — | 72.0s | /s/briz-cafe |
| a1 | app | ✓ | ✓ | ✓ | ✓ | 6542 | ✓ | 2 | 62.5s | /s/party-guestbook |
| a2 | app | ✓ | ✓ | ✓ | ✓ | 6410 | ✓ | 1 | 89.5s | /s/cats-vs-dogs |

## AC4 quality (independent judges)
- korica-bakery 5/5 — warm personalized RU copy, all 3 sections (о нас/меню/контакты), custom warm palette, responsive; nit: CSS-placeholder "map".
- artyom-portfolio 5/5 — dark themed, 3 named projects + about + mailto button; nit: letter-tile project placeholders.
- kai-music 5/5 — editorial link-in-bio, fluid type, animated equalizer, 3 link buttons; nit: socials point to platform homepages.
- briz-cafe 5/5 — seaside palette, hero/atmosphere/menu+prices/hours, mobile breakpoint; nit: gradient-placeholder images + dummy phone.
- party-guestbook 5/5 — glassmorphism, name+message form correctly wired to dbQuery (parameterized INSERT + SELECT render + 15s refresh, escapeHtml).
- cats-vs-dogs 5/5 — two vote buttons wired to dbQuery (UPDATE increment + SELECT counts, percentages in headers + bars, localStorage dedup).

The probes run via direct `hermes chat --quiet` in the operator HERMES_HOME — OUTSIDE the
Convex/Sendblue queue — so no synthetic inbound touched the operator's real iMessage.

AUDIT_VERDICT=PASS
