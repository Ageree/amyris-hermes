# Goal: Full feature audit → test → fix → retest of the Hermes Fleet (Amyris) app

## Objective

Drive a complete quality cycle over **every user-facing feature** of this app, in four
phases, tracked in **one canonical spreadsheet**:

1. **CATALOG** — Enumerate every feature across all four surfaces (web frontend,
   Convex control-plane, assistant brain/worker, fleet controller). For each, write a
   **user story** ("As a <role>, I can <action> so that <benefit>") and the
   **expected behaviour derived from the code** (states, validations, success/error
   paths). Record each as a row in the canonical tracker.
2. **TEST** — Test every user story. Document every error / divergence from expected
   behaviour, with severity and evidence.
3. **FIX** — Fix every **logistical** (logic/correctness) error and every **UX** error
   found in phase 2.
4. **RETEST** — Re-test every user behaviour after the fixes; confirm no regressions.

## Canonical tracker (single source of truth)

- `docs/feature-audit/features.json` — structured source of truth (one object per feature).
- `docs/feature-audit/feature-status.csv` — the human-readable **spreadsheet**, rendered
  from `features.json` by `docs/feature-audit/render_csv.py`. **This CSV is "the single
  canonical spreadsheet tracking the features status."**
- Agents update `features.json` (safe, no CSV-escaping foot-guns) then re-render the CSV.

## Working assumptions (Lead's defaults — EDIT THIS FILE to steer)

- **Catalog scope**: ALL features (incl. backend / fleet / controller). The TEST/FIX/RETEST
  phases prioritise **user-observable** behaviour (user stories + UX); pure-internal
  invariants are still cataloged and verified via existing tests where they exist.
- **Test safety (HARD CONSTRAINT)**: hermetic / test-seam only. Allowed: pytest suites,
  offline `docker compose` smoke, Playwright against a **local** dev server + the dev
  Convex deployment using **throwaway `tt-*` test tenants** (test seam). **Forbidden by
  default**: sending real messages to real iMessage/Telegram users, mutating production
  config, touching the operator's live fleet container, rotating keys, `npx convex deploy`
  to prod. A user story that can ONLY be verified by a live send is marked
  `blocked: needs operator-approved live test` — never executed silently.
- **Fix scope**: fix logistical + UX errors, prioritised by severity (crit→high→med→low).
  Each fix follows the repo's rules: GitNexus `impact` before editing a symbol, TDD,
  hermetic check left behind. Large/risky refactors are surfaced, not silently undertaken.
- **Isolation**: all work happens in the `worktree-feature-audit` git worktree; merged to
  `main` only after phase 4 is green (or when the user asks).

## Constraints

- Follow `~/.claude/rules/*` (coding style, testing, security, git) and the repo CLAUDE.md
  (GitNexus impact-analysis before edits; `detect_changes` before commits).
- No new dependencies unless unavoidable (ponytail). Deletion/simplification preferred.
- Never claim a phase done without running its verification and reading the output.

## Owner

The user owns this file and `acceptance.md`. The loop only appends to events / updates
continuation, budget, state, and the tracker + code under fix.
