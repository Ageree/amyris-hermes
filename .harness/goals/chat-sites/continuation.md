# Continuation — chat-sites

## Shipped (built + live-verified against dev:zany-tapir-501)
- **Convex backend** (additive, deployed): `sites` table (schema.ts); `convex/sites.ts`
  (`publish` action gated by the NARROW `SITES_PUBLISH_SECRET`, `getByHandle`,
  `_upsert`); `convex/lib/sitelib.ts` (handle validation, SQL guard, runtime
  injection, URL build); `convex/lib/turso.ts` (Platform API provisioning + libSQL
  `/v2/pipeline` data access via fetch); two httpActions in `http.ts`
  (`GET /s/:handle` serves the generated HTML on the `.convex.site` origin;
  `POST /site-data/:handle` proxies guarded SQL to the site's isolated Turso DB).
- **Hermes skill** `lab/skills/create-site/` (SKILL.md + scripts/publish.py),
  seeded by `worker.seed_create_site()` (wired into `main()`), kill-switch
  `CREATE_SITE_ENABLED`, allowlists CONVEX_URL/SITES_PUBLISH_SECRET/USER_ID/
  SITE_PUBLISH_PY through the terminal scrubber — and provably NOT WORKER_SECRET.
- **Convex env set** on dev: TURSO_PLATFORM_TOKEN, TURSO_ORG=ageree,
  TURSO_GROUP=sites, TURSO_LOCATION=aws-eu-west-1, SITES_PUBLIC_BASE, SITES_PUBLISH_SECRET.

## Verified
- `node control-plane/convex_e2e/sites.mjs` → 21/21 PASS (static serve, app
  provision+serve+insert+select, all trust-boundary rejections; cleans its Turso DB).
- `publish.py` live smoke: static + app published via the script, served + data OK.
- `lab/tests/test_create_site_seed.py` 4/4 + browser-harness regression 4/4.
- `tsc -p control-plane/tsconfig.json --noEmit` exit 0.

## Remaining (operator-gated go-live, NOT built into the live chat yet)
1. Deploy the updated `worker.py` to the operator's live worker (`deploy-worker.sh`
   into `~/.hermes-savedlab/worker/`) so `seed_create_site` runs and the skill loads.
2. Add `SITES_PUBLISH_SECRET` to the worker env (`~/.hermes-savedlab/.env`) and, for
   fleet containers, to the controller `_build_env`; restart the worker.
3. Then the full chat path works: user asks → agent builds + runs publish.py → URL reply.
- Optional: custom wildcard domain (`<handle>.<domain>`) instead of `/s/<handle>` —
  ~30 lines of middleware + DNS, architected for, not wired.

## Blocked
- Nothing. Backend is live; go-live is a deliberate operator step (touches the
  live assistant worker), documented above.

## Hygiene
- Turso platform token was pasted in chat → flag for rotation.
