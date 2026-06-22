# Acceptance criteria (the Auditor re-verifies each from scratch)

Phases are sequential. A later phase's criteria are only checked once the earlier phase
is marked complete in `state.json` (`phase` field).

## Phase 1 — CATALOG complete

- [ ] `docs/feature-audit/features.json` exists and parses as JSON (`python3 -c "import json;json.load(open('docs/feature-audit/features.json'))"`).
- [ ] `docs/feature-audit/feature-status.csv` exists and is re-rendered from the JSON
      (`python3 docs/feature-audit/render_csv.py` exits 0 and produces a CSV whose row
      count == len(features.json)).
- [ ] Coverage: every surface is represented — at least the WEB, control-plane (CP),
      assistant (ASST), and fleet-controller (CTRL) areas each have rows. Spot-check 5
      random features against the actual code: the `source_refs` resolve to real
      file:line and the `expected_behavior` matches the code.
- [ ] Every row has non-empty: `id`, `area`, `feature`, `user_story`,
      `expected_behavior`, `source_refs`, `verify_method`.

## Phase 2 — TEST complete (errors documented)

- [ ] The baseline verification commands were run and their output captured in
      `events.jsonl` / `continuation.md`:
  - `cd lab && python3 -m pytest -q` (network-free default)
  - `cd fleet/controller && python3 -m pytest -q tests/`
  - `cd web && npx tsc --noEmit` and `npm run build`
  - Playwright `cd web && npm run e2e` (against local dev server + dev Convex; if it
    cannot run hermetically, document why and which stories are `blocked`)
  - offline multi-tenant smoke `cd fleet/local && docker compose up --build --abort-on-container-exit --exit-code-from seed` (if docker available; else document `blocked`)
- [ ] Every feature row has `p2_test_status` ∈ {pass, fail, blocked} and non-empty
      `p2_evidence` (command + observed result, or reason for `blocked`).
- [ ] Every failure has `error_found` (what diverged), `severity` ∈ {crit, high, med, low},
      and `error_type` ∈ {logical, ux}.

## Phase 3 — FIX complete

- [ ] Every row where `error_type` ∈ {logical, ux} and `severity` ∈ {crit, high, med, low}
      has `p3_fix_status` ∈ {done, deferred} — and `deferred` rows carry a one-line reason.
- [ ] Each `done` fix has a `p3_fix_ref` (file:line or commit) and left a hermetic check.
- [ ] No regressions introduced: `cd lab && python3 -m pytest -q` and
      `cd fleet/controller && python3 -m pytest -q tests/` are GREEN; `cd web && npx tsc
      --noEmit` is clean and `npm run build` exits 0.

## Phase 4 — RETEST complete

- [ ] Every row that was `fail` in phase 2 has `p4_retest_status` ∈ {pass, fail, blocked}.
- [ ] All previously-failing user-observable stories that were fixed now `pass`.
- [ ] Full suites green (same commands as Phase 3) — captured in the final audit.

## AUDIT_VERDICT

PASS only when the criteria for the CURRENT phase (per `state.json.phase`) are all met.
The final PASS (goal done) requires Phase 4 complete with no open crit/high
logistical/UX errors.
