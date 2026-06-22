# Completion Audit 3 — feature-audit Phases 3 (FIX) + 4 (RETEST)

Re-verified from scratch by running every command in the worktree
`/Users/saveliy/Documents/Amyris/.claude/worktrees/feature-audit`. Read-only except this report.

## Checks

| check | status | evidence (real command output) |
|---|---|---|
| Lab suite green | PASS | `cd lab && python3 -m pytest` → `531 passed, 22 skipped, 2 warnings in 2.43s`, exit 0, no failures |
| tiers_drift collected + passes | PASS | `pytest -q tests/test_tiers_drift.py` → `1 passed` (`.` 100%), exit 0 |
| Controller suite green | PASS | `cd fleet/controller && python3 -m pytest -q tests/` → `83 passed, 1 warning in 0.13s`, exit 0 |
| stale_ttl test passes | PASS | `pytest -q tests/ -k stale_ttl` → `1 passed, 82 deselected in 0.05s`, exit 0 |
| Web typecheck | PASS | `cd web && npm run typecheck` (`tsc --noEmit`) → exit 0, no output errors |
| Web build | PASS | `npm run build` → `✓ Generating static pages (7/7)`, 5 routes (/ /connect /dashboard /signin /_not-found), exit 0 |
| WEB-01 Playwright retest | PASS | `npx playwright test landing.spec.ts --reporter=list` → `4 passed (17.1s)`; previously-RED test `has a sign-in affordance linking to /signin` now ✓ (2.4s), GET /signin 200 |
| CTRL-13 code: config.py default 240.0 | PASS | `config.py:145` → `stale_ttl_s=_float_env("STALE_TTL_S", 240.0)` |
| WEB-04 code: TierGrid "messages / month" | PASS | `TierGrid.tsx:101` → `{tier.msgQuota.toLocaleString()} messages / month`; no "turns / mo" anywhere (only word "returns" in unrelated comments/tests) |
| All 3 quota components use "messages / month" | PASS | `marketing/TierGrid.tsx:101`, `dashboard/TierCard.tsx:80`, `connect/ConnectWizard.tsx:221` all read "messages / month" (note: TierCard/ConnectWizard live under dashboard/connect, not the paths in the brief) |
| WEB-31 fix present | PASS | `lab/tests/test_tiers_drift.py` collected by lab gate and passes (asserts web/lib/tiers.ts agrees with control-plane/convex/billing/tiers.ts) |
| Tracker rows updated (4 ids) | PASS | features.json: WEB-01/WEB-04/WEB-31/CTRL-13 all have `p3_fix_status="done"`, non-empty `p3_fix_ref`, `p4_retest_status="pass"` |
| render_csv.py exits 0 | PASS | `python3 docs/feature-audit/render_csv.py` → exit 0 |

## Suite counts
- Lab: 531 passed, 22 skipped (0 failures)
- Controller: 83 passed (0 failures)
- Web: typecheck exit 0, build exit 0 (5 routes)
- Playwright (landing.spec.ts): 4 passed, 0 failed

## Notes
- All 4 fixes present in code; the previously-RED landing sign-in test now passes; no regressions in any suite.
- Minor doc nit (not a defect): the brief lists `components/marketing/TierCard.tsx` and `components/onboarding/ConnectWizard.tsx`; the actual files are `components/dashboard/TierCard.tsx` and `components/connect/ConnectWizard.tsx`. Both contain the correct "messages / month" copy.

AUDIT_VERDICT=PASS
