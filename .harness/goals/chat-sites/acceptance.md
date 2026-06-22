# Acceptance criteria — chat-sites

Each row is re-verified from scratch by the isolated auditor. Verification
commands run from the worktree root unless noted.

| # | Criterion | How to verify |
|---|-----------|---------------|
| A1 | `sites` table exists in schema with `handle` (unique index), `kind` (static\|app), `html`, optional Turso fields, `userId`. | `control-plane/convex/schema.ts` defines `sites` with `by_handle` index. `tsc` clean. |
| A2 | Pure helpers exist & are correct: handle validation (slug, reserved words, length≤63) and SQL guard (single statement, blocks ATTACH/DETACH/PRAGMA-escape, length cap). | `control-plane/convex/lib/sitelib.ts`; covered by the e2e rejection cases (A7). |
| A3 | Turso lib provisions a DB end-to-end via Platform API (group ensure → create db → scoped token → apply schema via `/v2/pipeline`) and can exec guarded SQL. | `control-plane/convex/lib/turso.ts`. Proven by the live e2e (A8). |
| A4 | `sites:publish` Convex **action** gated by `WORKER_SECRET`: validates handle, for `kind=app` provisions Turso + applies schema, upserts the row, returns `{url, handle}`. Wrong secret → throws. | Code present; e2e A7/A8 exercise it incl. a wrong-secret rejection. |
| A5 | `GET /s/:handle` httpAction returns the raw generated HTML (Content-Type text/html) with the data-API base injected; unknown handle → 404. | Live `curl https://<dep>.convex.site/s/<handle>` returns the HTML; unknown → 404. |
| A6 | `POST /site-data/:handle` httpAction proxies guarded SQL to the site's Turso DB and returns rows; non-app or unknown handle → 4xx; bad SQL → rejected. | Live curl insert+select returns the row; ATTACH/multi-stmt → rejected. |
| A7 | Hermes skill `create-site` exists (SKILL.md teaching the static/app contract + `dbQuery` helper + public-apps-only steer) and `publish.py` calls the action. Wired into worker seeding like browser-harness. | `lab/skills/create-site/SKILL.md` + `scripts/publish.py`; `worker.py` seeds it; `lab/tests/test_create_site_seed.py` green. |
| A8 | **Live end-to-end**: deploy to dev:zany-tapir-501 with TURSO_* env set; publish a STATIC site (served & matches) AND an APP site (guestbook): GET serves the page, POST /site-data inserts a row and SELECT returns it; teardown leaves no probe junk. | `node control-plane/convex_e2e/sites.mjs` exits 0 with all assertions PASS. |
| A9 | `tsc` clean in control-plane; existing tests still green (lab pytest subset for touched areas + worker seed test); no existing webhook/route regressed. | `cd control-plane && npx tsc -p tsconfig.json --noEmit` exit 0; `cd lab && python -m pytest tests/test_create_site_seed.py -q` green; existing routes untouched in http.ts diff. |

## Verification commands (the auditor MUST run these)
```bash
# typecheck (control-plane)
cd control-plane && npx tsc -p tsconfig.json --noEmit ; echo "tsc=$?"
# skill seed unit test
cd lab && python -m pytest tests/test_create_site_seed.py -q
# live end-to-end (requires dev deploy + TURSO_* env already set on the deployment)
node control-plane/convex_e2e/sites.mjs   # prints PASS/FAIL per step, exit 0 = all green
```

## Done = all rows PASS in an isolated audit (AUDIT_VERDICT=PASS).
