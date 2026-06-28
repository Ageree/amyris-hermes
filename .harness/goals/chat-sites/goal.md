# Goal — "Create a site/app in chat" (Poke-parity + Turso)

## Objective
Add a Poke-style feature to the existing Hermes Fleet assistant: a user, in chat
(iMessage/Telegram), asks the assistant to build them a personalized website or a
small interactive web app. The assistant generates it, deploys it, and replies
with a live public URL. This is a **superset of Poke**:

- **static** sites — personalized pages (portfolio / landing / link-in-bio), like Poke.
- **app** sites — interactive, data-backed mini-apps (guestbook, poll, counter,
  public wall, tracker). Each `app` gets its OWN isolated Turso (libSQL/SQLite)
  database, provisioned on demand, reached only through a server-side proxy that
  holds the scoped DB token. The generated client JS never sees the token.

## Locked decisions (user-approved 2026-06-22)
1. Scope = superset (static pages + Turso-backed interactive apps). Turso IS used.
2. URL = served from a **separate origin** (`*.convex.site/s/<handle>`), NOT the
   dashboard origin, so generated (LLM/possibly prompt-injected) JS cannot reach
   the dashboard's auth cookies. Architected so a custom wildcard subdomain can be
   added later as a thin rewrite. User deferred the domain choice to me.
3. Build is **additive** to the live system. Do not disturb the existing
   webhooks / fleet / auth. Reuse userId tenancy, Convex, Vercel, Hermes skills.

## Architecture
- **Convex** = control plane + site registry (`sites` table) + serving
  (`GET /s/:handle` returns the raw generated HTML document) + data proxy
  (`POST /site-data/:handle` runs guarded SQL against that site's Turso DB).
- **Turso** = one isolated SQLite DB per `app` site. Provisioned via the Platform
  API from a Convex action (group ensure → db create → scoped token mint → apply
  schema via the libSQL HTTP `/v2/pipeline` endpoint). Org slug `ageree`.
- **Hermes skill** `create-site` = teaches the agent to generate a single
  self-contained HTML document (+ a `schema.sql` for apps) and call `publish.py`,
  which invokes the Convex `sites:publish` action (gated by `WORKER_SECRET`).
- Generated `app` HTML talks to its data via an injected `dbQuery(sql, args)`
  helper that fetches the same-origin `/site-data/<handle>` proxy.

## Constraints
- Turso platform token + per-DB scoped tokens stay server-side (Convex env / the
  `sites` row). Never returned to the browser.
- Trust boundaries are NOT lazy: handle validation, SQL guard, publish auth gate.
- v1 data API is OPEN (public read+write to the site's own isolated DB) — fine for
  public apps (guestbook/poll/wall). Private/personal apps need viewer auth (v2).
  SKILL.md must steer the agent to public-data apps only for v1.
- Must pass `tsc` and deploy additively to dev:zany-tapir-501 without breaking the
  existing deployment.

## Out of scope (v1)
- Custom wildcard domain / vanity subdomains (architected for, not wired).
- Per-visitor auth on app data (open public apps only).
- Cloudflare Workers per-user arbitrary code isolation (the "full custom apps" tier).
