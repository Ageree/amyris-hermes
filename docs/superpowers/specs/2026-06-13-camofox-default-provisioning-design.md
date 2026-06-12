# Design — Camoufox as the default browser for provisioned Hermes agents

- **Date:** 2026-06-13
- **Status:** Draft for review
- **Author:** pairing session (Claude)
- **Related:** `specs/001-saved-content-agent/` (US3 one-click provisioning), `lab/REPORT.md` (P1B Camofox)

## Goal

Make **every Hermes agent default to the Camoufox (stealth Firefox) browser backend** —
both *when it is created* (provisioning) and *when it runs* (usage) — without per-agent
manual setup, and with **per-tenant isolation** so one user's logged-in browser sessions
are never visible to another.

### In scope
- The mechanism that makes Camoufox the default browser for a provisioned agent.
- Per-tenant browser-profile isolation + persistence ("log-in-once" per tenant).
- The shared Camoufox server as infrastructure (not on the operator's Mac).
- Integration points the provisioning flow must hit.

### Out of scope (separate specs)
- The full multi-tenant control plane: signup → tenant record, inbound-number → tenant
  routing, billing, the website "one-click" button. This spec only defines the **Camoufox
  slice** of provisioning and names the hooks it needs.

## Background — how Camoufox is selected today

Camoufox is **not** a code change. Hermes already ships a `camofox` browser backend
(`tools/browser_camofox.py`, release v0.7.0). Selection is **purely by environment
variable**:

- `is_camofox_mode()` returns true iff `CAMOFOX_URL` is set **and** `BROWSER_CDP_URL`
  is not. When true, all browser tool calls route to the Camofox REST server instead of
  the default local Chromium (`agent-browser`).
- There is **no `config.yaml` switch** for enabling it — `config.yaml: browser.camofox`
  only holds sub-options. So "default on" ⇒ **`CAMOFOX_URL` must be present in every
  Hermes process's environment**, and a server must answer at that URL.

Verified working 2026-06-12: a live Hermes run returned a `Firefox/135.0` user-agent and
the Camofox server logged `POST /tabs → session created → navigate → snapshot → DELETE
/sessions (storage state persisted)`.

## Key insight — isolation is (almost) free via `HERMES_HOME`

`tools/browser_camofox_state.get_camofox_identity()` derives the Camofox identity
**deterministically from `HERMES_HOME`**:

```
user_id     = "hermes_" + uuid5(NAMESPACE_URL, f"camofox-user:{HERMES_HOME}/browser_auth/camofox")[:10]
session_key = "task_"   + uuid5(NAMESPACE_URL, f"camofox-session:{HERMES_HOME}:{task_id}")[:16]
```

Consequences:
- **Different `HERMES_HOME` ⇒ different `user_id` ⇒ a separate, persistent Firefox
  profile per tenant** on the *same* shared Camofox server. No per-tenant `user_id`
  bookkeeping needed.
- This only takes effect when **`managed_persistence: true`** in that agent's
  `config.yaml`. When false (the current default) each session gets a *random* ephemeral
  userId → no persistence, re-login every time.
- The worker already launches Hermes with a per-instance `HERMES_HOME`
  (`hermes_bridge.py:92` → `env = {**os.environ, "HERMES_HOME": hermes_home}`), so the
  routing primitive already exists.

## Design

### Topology
```
                         ┌─────────────────────────────────────┐
  inbound iMessage  ──▶  │ worker (routes inbound# → tenant)    │
  (Sendblue)             │  spawns Hermes with:                 │
                         │    HERMES_HOME=<per-tenant dir>      │
                         │    CAMOFOX_URL=http://camofox:9377   │  (default, baked in)
                         └───────────────┬─────────────────────┘
                                         │ REST (per-tenant user_id, auto from HERMES_HOME)
                         ┌───────────────▼─────────────────────┐
                         │ ONE shared Camofox server (Linux)   │
                         │  persistent profile per user_id:     │
                         │  /data/camofox/profiles/<hash>/...   │
                         └─────────────────────────────────────┘
```

### Four levers to make it the default
1. **Shared Camofox server as infra.** Run `@askjo/camofox-browser@1.11.2` as a managed
   service on the Linux host (Docker/compose/systemd), reachable at a stable
   `CAMOFOX_URL` (e.g. `http://camofox:9377` on the internal network). One server serves
   all tenants; profiles are isolated by `user_id`.
2. **`CAMOFOX_URL` in the base environment.** Bake it into the deployment env (compose
   `environment:`, k8s env, or the worker's base `.env`) so *every* spawned Hermes
   inherits it. No per-tenant edit required for usage. (Env-template, **not** a fork code
   change — survives upstream merges.)
3. **`managed_persistence: true` in the per-tenant `config.yaml` template.** This is the
   one default to flip vs upstream. Set it in the `config.yaml` that provisioning writes
   into each tenant's `HERMES_HOME`.
4. **Per-tenant `HERMES_HOME` at creation.** Provisioning allocates
   `HERMES_HOME=<root>/tenants/<tenantId>` and the worker routes each inbound number to
   that tenant's `HERMES_HOME`. Isolation + persistence then follow automatically.

### Provisioning integration (the "created with" part)
When a tenant is created, the provisioning step MUST:
1. `mkdir` `HERMES_HOME=<root>/tenants/<tenantId>` (0700).
2. Write `<HERMES_HOME>/config.yaml` from a template with `browser.camofox.managed_persistence: true`
   (plus model/toolset defaults). Reuse Hermes `ensure_hermes_home()` to seed structure,
   then patch the camofox key.
3. Write `<HERMES_HOME>/.env` with the tenant's secrets (Sendblue identity, model key).
   `CAMOFOX_URL` can be inherited from base env OR written here explicitly.
4. Register the tenant's inbound number → `HERMES_HOME` in the worker's routing table
   (control-plane: extend schema with a `tenants` table; out of scope here but named).
No Camofox login is required at creation — the profile is created lazily on first browse;
the tenant logs into sites on demand (optionally via the Camofox VNC URL for visual login).

### Local dev parity
The single-agent local setup is the same design with one tenant: `~/.camofox/toggle.sh on`
+ `managed_persistence: true` in `~/.hermes/config.yaml`. Kept **off by default on the Mac**
to avoid the always-warm Firefox heating the laptop (see memory `mac-cleanup-after-tests`);
the always-on server belongs on the Linux host, not the dev Mac.

## Concrete artifacts to build
- [ ] `infra/camofox/` — Dockerfile/compose (or systemd unit) running
  `@askjo/camofox-browser@1.11.2`, persistent volume at `/data/camofox`, healthcheck on
  `/health`, `--restart unless-stopped`.
- [ ] Base-env default: `CAMOFOX_URL` in the worker/deploy env template.
- [ ] `provision_tenant(tenantId, ...)` helper: creates `HERMES_HOME`, seeds `config.yaml`
  with `managed_persistence: true`, writes `.env`. (Reference impl in `lab/skeleton/` or
  control-plane.)
- [ ] Worker routing: inbound number → tenant `HERMES_HOME` (depends on the `tenants`
  table — coordinate with the multi-tenant control-plane spec).
- [ ] Smoke test: two tenants browse the same site; assert distinct Camofox `user_id`
  and that tenant A's cookies are absent in tenant B's profile.

## Security notes
- **Isolation is the whole point.** Verify per-tenant profiles never share cookies; the
  deterministic `user_id` from `HERMES_HOME` is the guarantee — protect `HERMES_HOME`
  allocation (no path collisions, 0700).
- The Camofox server has `allow_private_urls`/SSRF settings — review before exposing on a
  shared host; keep it on a private network, not public.
- Login flows: for sites needing auth, expose the per-session VNC URL to the *owning*
  tenant only.

## Open questions / assumptions
- **Deployment target not yet decided** (VPS / Cloud Run / Modal / container-per-tenant).
  This design assumes a shared Linux host running one Camofox server + a worker that
  spawns per-tenant Hermes by `HERMES_HOME`. If you move to container-per-tenant, the
  only change is *where* `CAMOFOX_URL` is injected (sidecar vs shared service); the
  identity/isolation model is unchanged.
- One shared Camofox server vs a pool: start with one; scale horizontally behind a load
  balancer keyed by `user_id` if browser concurrency becomes the bottleneck.
