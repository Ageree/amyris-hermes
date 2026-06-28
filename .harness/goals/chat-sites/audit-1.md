# Audit 1 — chat-sites (isolated re-verification)

Auditor re-verified every acceptance row from scratch against the real repo and
the live `dev:zany-tapir-501` deployment. No prior report trusted. Source files
read directly; commands run with real output captured below.

## Per-criterion results

| # | PASS/FAIL | Evidence |
|---|-----------|----------|
| A1 | **PASS** | `control-plane/convex/schema.ts` defines `sites` with `handle`, `userId: optional id("users")`, `kind: union("static","app")`, `html`, optional Turso fields (`tursoDbName`/`tursoHostname`/`tursoToken`/`schemaSql`), `version`, `createdAt`, `updatedAt`. Indexes `.index("by_handle", ["handle"])` (unique public key) and `by_user`. `tsc -p tsconfig.json --noEmit` → `TSC=0`. |
| A2 | **PASS** | `control-plane/convex/lib/sitelib.ts`. `validateHandle`: lowercases, length 2..63, DNS-label regex `^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$`, rejects `--`, rejects a 22-word `RESERVED_HANDLES` set (`s`, `site-data`, `app`, `telegram`, `auth`, …). `guardSql`: trims, rejects empty, caps `MAX_SQL_LEN=10_000`, blocks `\b(attach\|detach)\b` case-insensitive. Both exercised live in A8 (bad handle `a` rejected; `ATTACH` → 400). |
| A3 | **PASS** | `control-plane/convex/lib/turso.ts` provisions via Platform API: `ensureGroup` (GET→POST idempotent, 409-tolerant) → `createDatabase` → `mintToken` (`?authorization=full-access`) → `applySchema` (splits on `;`, runs each stmt). Data plane `execSql` POSTs libSQL HTTP `/v2/pipeline` with `execute`+`close`, bound args via `toArg` (typed: null/integer/float/text), decodes via `fromCell`. Proven live in A8 (provision + INSERT/SELECT). No npm deps — plain `fetch`. |
| A4 | **PASS** | `control-plane/convex/sites.ts` `publish` is an `action` that calls `assertSitesPublisher(args.secret)` FIRST (gates on **SITES_PUBLISH_SECRET**, NOT WORKER_SECRET), validates handle, checks html non-empty + ≤1MB, requires `SITES_PUBLIC_BASE`, enforces owner + kind-stability on republish, provisions Turso for `kind=app` (reuse-on-republish, idempotent), upserts via `internal.sites._upsert`, returns `{url, handle, kind}`. Live: wrong secret → `error` `"unauthorized publisher"`; correct secret → success. |
| A5 | **PASS** | `control-plane/convex/http.ts` `GET /s/` httpAction reads `internal.sites.getByHandle`, injects runtime (apiBase = `url.origin` of the `.convex.site` request), returns `text/html; charset=utf-8` (+`x-content-type-options: nosniff`); unknown/empty handle → 404 HTML. Live: `GET /s/<static>` → 200 text/html with marker, NO `window.dbQuery`; `GET /s/<app>` → 200 with `window.dbQuery` + `/site-data/<handle>`; `GET /s/does-not-exist-*` → 404. |
| A6 | **PASS** | `POST /site-data/` httpAction: `getByHandle` → 404 if unknown; non-app or missing turso fields → 400 `"site has no data backend"`; bad JSON → 400; `guardSql` failure → 400; else `execSql` returns rows. Live: INSERT affected 1 row; SELECT returns row `name=Saveliy`; `ATTACH` → 400 (error contains "ATTACH"); `SELECT 1` on the static site → 400 "no data backend". |
| A7 | **PASS** | `lab/skills/create-site/SKILL.md` (front-matter + static/app contract + `dbQuery(sql,args)` helper doc + explicit "v1 apps are PUBLIC … do NOT store private data" steer). `lab/skills/create-site/scripts/publish.py` (stdlib-only; POSTs `sites:publish` to `$CONVEX_URL/api/action` with `SITES_PUBLISH_SECRET`, prints the returned URL). `worker.seed_create_site` is wired into `main()` right after `seed_browser_harness` (idempotent, kill-switch `CREATE_SITE_ENABLED`, fail-soft). `lab/tests/test_create_site_seed.py` → **4 passed** incl. `test_seed_never_exposes_worker_secret`. |
| A8 | **PASS** | `node control-plane/convex_e2e/sites.mjs` → **21 passed, 0 failed**, `ALL PASS`, `E2E_EXIT=0`. Cleanup line: `cleanup deleted turso db s-e2e-app-mqpbclaz-f3619df7 (HTTP 200)`. Independent Turso list afterward: **total dbs: 0, s-e2e leftover: []** — no probe junk. |
| A9 | **PASS** | `tsc` exit 0; seed test green; change surface is purely **additive** — `messages.ts`/`fleet.ts`/`pairing.ts`/`lib/identity.ts` show empty diff vs origin/main; `http.ts` only ADDS the `/s/`, `/site-data/`, OPTIONS routes BEFORE `auth.addHttpRoutes(http)` (existing Sendblue + Telegram webhooks unchanged); `lib/auth.ts` only ADDS `assertSitesPublisher`; `schema.ts` is +21/-0; `api.d.ts` only ADDS `sites`/`lib/sitelib`/`lib/turso`. |

## Command output snippets

```
$ cd control-plane && npx tsc -p tsconfig.json --noEmit ; echo "TSC=$?"
TSC=0

$ cd lab && python3 -m pytest tests/test_create_site_seed.py -p no:ddtrace -p no:anyio -p no:asyncio -rA
PASSED tests/test_create_site_seed.py::test_seed_installs_skill_and_allowlists_env
PASSED tests/test_create_site_seed.py::test_seed_never_exposes_worker_secret
PASSED tests/test_create_site_seed.py::test_seed_idempotent_and_merges_existing
PASSED tests/test_create_site_seed.py::test_seed_kill_switch_off_is_noop
4 passed, 1 warning in 0.10s

$ node control-plane/convex_e2e/sites.mjs   (live dev:zany-tapir-501, with SITES_PUBLISH_SECRET + TURSO_PLATFORM_TOKEN)
  PASS  publish static returns success
  PASS  static url is correct
  ... (21 PASS lines total) ...
  PASS  data ATTACH rejected (400)
  PASS  data on static site rejected (400)
  PASS  GET unknown handle -> 404
  cleanup  deleted turso db s-e2e-app-mqpbclaz-f3619df7 (HTTP 200)
[chat-sites e2e] 21 passed, 0 failed
ALL PASS  / E2E_EXIT=0

$ curl -s -H "Authorization: Bearer $TT" .../organizations/ageree/databases | (filter s-e2e)
total dbs: 0
s-e2e leftover: []

$ git diff --stat origin/main   (+ untracked new files)
 control-plane/convex/_generated/api.d.ts |   6 ++   (ADD only)
 control-plane/convex/http.ts             | 101 +++   (ADD only, before auth.addHttpRoutes)
 control-plane/convex/lib/auth.ts         |  15 ++    (ADD assertSitesPublisher only)
 control-plane/convex/schema.ts           |  21 ++    (+21/-0, sites table)
 lab/skeleton/worker.py                   |  54 +++   (ADD seed_create_site + 1 call site)
 (untracked new: sites.ts, lib/sitelib.ts, lib/turso.ts, convex_e2e/sites.mjs,
  lab/skills/create-site/**, lab/tests/test_create_site_seed.py)
 messages.ts / fleet.ts / pairing.ts / lib/identity.ts: NO diff (untouched)
```

## Security sanity-check (read, not just trusted)

- **publish gate is the narrow secret, not WORKER_SECRET.** `sites.publish` →
  `assertSitesPublisher(args.secret)` → compares `process.env.SITES_PUBLISH_SECRET`
  with a constant-time `safeEqual`; throws `"unauthorized publisher"`, and fails
  closed when the env is unset. WORKER_SECRET (the queue master gate) is never
  referenced by the sites code. Rationale is documented in `lib/auth.ts`: the
  publish script runs in the agent's `terminal` (untrusted inbound), so the secret
  it can read is deliberately scoped to "publish sites only".
- **Turso token never reaches a client.** `getByHandle` is an `internalQuery`
  (not callable from a browser). `GET /s/:handle` calls `injectRuntime`, which
  only emits `{ handle, api }` into `window.__SITE` — never `tursoToken`. The
  `dbQuery` helper POSTs to the same-origin `/site-data/<handle>` proxy; the token
  is read server-side in the `POST /site-data` httpAction and passed to `execSql`
  only. The token column is stored server-side in the `sites` row. The HTML body
  never contains the token (live e2e served pages do not include it).
- **guardSql** rejects empty SQL, caps at 10 000 chars, and blocks
  `ATTACH`/`DETACH` (the cross-DB escape) case-insensitively. libSQL Hrana runs
  exactly one statement per `execute`, and all values are bound args (`toArg`),
  so stacked-statement and string-interpolation injection are structurally
  prevented. **validateHandle** enforces a DNS-label slug (2..63, no leading/
  trailing/consecutive dash) and a reserved-words set incl. `s`, `site-data`,
  `telegram`, `sendblue`, `auth`.
- **Separate origin.** The generated HTML is served from the `.convex.site` HTTP
  router (httpActions returning `text/html`), distinct from the Vercel dashboard
  origin — so prompt-injected generated JS cannot reach dashboard auth cookies.
  Routes are appended to the same router BEFORE `auth.addHttpRoutes(http)`, and
  the pre-existing `/sendblue/inbound/` and `/telegram/inbound` routes plus the
  `messages`/`fleet` functions are byte-for-byte untouched (empty diff).
- **Seed never leaks WORKER_SECRET.** `seed_create_site` allowlists only
  `CONVEX_URL / SITES_PUBLISH_SECRET / USER_ID / SITE_PUBLISH_PY` into the
  terminal `env_passthrough`; `test_seed_never_exposes_worker_secret` asserts
  `WORKER_SECRET` is NOT in the allowlist and passes.

## Verdict

All 9 acceptance criteria pass on independent re-verification (tsc clean, 4/4 seed
tests green incl. the WORKER_SECRET-exclusion security test, 21/21 live e2e
assertions green with full Turso teardown and zero leftover probe DBs, change
surface purely additive with the existing webhooks/fleet/auth untouched).

AUDIT_VERDICT=PASS
