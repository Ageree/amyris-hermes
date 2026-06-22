# Audit 2 — Phase 2 (TEST) verification

Independent verification was performed by the `phase2-test-mapping` workflow: 4 per-surface
agents assigned status+evidence to all 123 rows, then 5 independent adversarial agents
re-verified each claimed FAIL from scratch (reading file:line, refuting by default).

| check | status | evidence |
|---|---|---|
| baseline suites run + captured | PASS | lab 530 passed/22 skip; controller 82 passed; web tsc 0 + build exit0; docker isolation smoke seed exit0; Playwright landing+auth-gate 5/6 |
| every row has p2_test_status ∈ {pass,fail,blocked} | PASS | validator: 0 problems; counts pass112/fail4/blocked7 = 123 |
| every row has non-empty p2_evidence | PASS | validator: 0 empty |
| every failure has error_found+severity+error_type | PASS | validator: 0 problems; 4 fails all low + classified |
| claimed bugs adversarially verified | PASS | 5 claims → 3 real, 1 stale_test (WEB-01), 1 not_a_bug (CTRL-11) |

## Confirmed errors → Phase 3
- WEB-01 (ux, low) — STALE TEST: product fine (Hero CTA covers top-fold sign-in), `landing.spec.ts:32` asserts pre-redesign header click. Fix = update the test.
- WEB-04 (ux, low) — real: "turns/mo" (TierGrid) vs "messages/month" (wizard+dashboard). Fix = unify noun.
- WEB-31 (logical, low) — real: `web/lib/tiers.ts` mirrors `control-plane/.../billing/tiers.ts`, no drift guard (agree now). Fix = add drift check.
- CTRL-13 (logical, low) — real: `config.py:145` STALE_TTL_S default 90s contradicts docs (240). Fix = raise default.

## Not actioned
- CTRL-11 (placement RAM=40) — not_a_bug: documented ponytail ceiling, test_placement asserts it.

## Blocked (7) — verified via hermetic alternatives, not the disabled seam
6 web + 1 control-plane rows require the double-gated `testing:*` seam (ALLOW_TEST_SEED unset on
the promoted dev:zany-tapir-501) or a real channel send. Not run (no prod-config mutation / no live
sends). Their invariants are covered by lab unit tests + the offline docker isolation smoke.

AUDIT_VERDICT=PASS
