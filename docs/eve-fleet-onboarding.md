# Eve Fleet — per-user onboarding / login handoff

**Date:** 2026-06-28 · Companion to [eve-fleet-spec.md](./eve-fleet-spec.md) component #6.

## The problem

Each user gets a container running headless Chrome (`:9222`, profile at
`$HERMES_HOME/chrome-profile`) that is meant to hold **their** Yandex login + linked card.
On the **first** order that profile is empty — there is no Yandex session and no card. The
agent must NOT log in for the user (it can't receive their SMS, and we never want the brain
typing card numbers — see `order.py` `GUARD_PAY`). So the user has to log into **their**
Yandex and add **their** card **once**, by hand, inside that exact Chrome session. After that
the cookies/card persist on the container disk (`HERMES_HOME`, GCS-mirrored) and every later
order just runs.

This is the per-user equivalent of browser-use cloud's `live_url`: a live, interactive view
of one specific container's Chrome, handed to one specific user, once.

## Trigger flow

```
inbound order ─▶ drainer (scoped poller, USER_ID set)
                   └─▶ order.py  (attach ORDER_CDP_URL=http://127.0.0.1:9222)
                         └─▶ hits Yandex auth wall, profile not logged in
                               └─▶ returns { needs: "NEED_LOGIN", ... }   ← THIS PR's order.py edit
                   ◀── poller sees needs=="NEED_LOGIN"
                   ├─▶ mint short-lived per-user handoff URL (see wiring)
                   └─▶ send URL to the user over THEIR channel (Telegram / iMessage)
                         with: "залогинься в Яндекс и привяжи карту — потом повтори заказ"
user opens URL ─▶ live view of THAT container's Chrome ─▶ logs in + adds card (human)
                   └─▶ profile persists ─▶ next order runs, no NEED_LOGIN
```

`order.py` change (this PR): a `GUARD_LOGIN` snippet appended to both task guards instructs
the agent to **return `NEED_LOGIN` and stop** if Yandex demands sign-in on a not-logged-in
profile, and `NEED_LOGIN` is added (first, so it wins over `NEED_CARD`) to the result `needs`
field. The poller wiring (mint URL + send over channel) belongs to the scoped drainer
(spec #1) and is **not** built here — `order.py` only emits the signal.

> ponytail: no "is login done yet?" polling. The handoff is human-gated and one-shot — the
> next order attempt is the check: it either succeeds or re-emits `NEED_LOGIN`. Re-send the
> URL on the next `NEED_LOGIN`. Upgrade path = a `loginState` heartbeat if users get stuck.

## Live-view approach — decision

| Option | What it is | Headless on GCP? | Cost to ship |
|---|---|---|---|
| **(a) proxy `:9222`** | reverse-proxy the container's CDP port; user opens Chrome's **built-in** DevTools frontend (`devtoolsFrontendUrl`), uses its Screencast to see+drive the page | ✅ native to headless Chrome, zero extra process | **near-zero code** — just an auth-gated proxy route |
| (b) `Page.startScreencast` mini-page | a ~150-line static page: CDP screencast frames → `<canvas>`, forward mouse/keys via `Input.*` | ✅ | ~1 small HTML + ws proxy |
| (c) noVNC | Xvfb + headful Chrome + x11vnc + websockify + noVNC | ⚠️ needs an X server the headless container doesn't have | heavy: 4 new processes/deps |

**Recommendation for v1: (a) proxy `:9222`.** It's the lightest that works headless: Chrome's
remote-debugging port already serves the target list (`/json`), the bundled DevTools frontend
(`/devtools/...`), AND the CDP websocket — so an auth-gated reverse proxy is the **entire**
implementation, no new code in the container and no new deps. DevTools' Screencast view is
interactive (it forwards clicks/keystrokes over CDP `Input.*`), so the user can complete the
Yandex phone+SMS login and add a card, and it all persists to the on-disk profile.

(c) is out — headless Chrome renders nothing to an X display, so noVNC would need a whole
Xvfb+headful stack. (b) is the **upgrade path**, not v1 (see ceilings).

## Exact wiring for (a) — keep v1 tiny

Reachability (no new published ports, no `docker_driver` change): the container's Chrome binds
`127.0.0.1:9222` **inside** the container. The handoff reverse proxy runs on the **same host**
(the controller host) and reaches that port over the docker bridge:
`docker inspect <container> -f '{{.NetworkSettings.IPAddress}}'` → `http://<bridge-ip>:9222`.

```
user ──TLS──▶ https://onboard.<host>/u/<userId>/?t=<token>
                 │  (host ingress: the existing controller-host reverse proxy / Caddy / nginx)
                 ▼
          handoff proxy  (per-user, token-gated)
                 │  verifies <token> (HMAC over userId, exp ≤ 15 min, signed with WORKER_SECRET)
                 │  looks up userId → container bridge-ip
                 │  REWRITES Host header → 127.0.0.1:9222   ← REQUIRED, see ceiling
                 ▼
          http://<bridge-ip>:9222   (the container's headless Chrome CDP)
```

URL minting (poller side, spec #1 — documented here, not built): on `needs=="NEED_LOGIN"`,
the drainer asks the controller for a handoff URL for `userId`; the controller signs a
short-lived token `HMAC(WORKER_SECRET, userId|exp)`, resolves the user's running container,
and returns `https://onboard.<host>/u/<userId>/?t=<token>`. The drainer sends that one line to
the user over their channel. The proxy route maps `/u/<userId>/` → that user's container only;
the token binds the URL to that `userId` and expires.

> The user lands on `/u/<userId>/json/list`-derived `devtoolsFrontendUrl` (or the proxy
> redirects straight to it). One Chrome target = the order tab; the user clicks Screencast,
> logs in, adds the card, closes the tab.

## Security (per-tenant) — non-negotiable, because CDP = full machine power

CDP on `:9222` is **unauthenticated, total control** of that Chrome: arbitrary JS, every
cookie, navigate anywhere, even local file reads. So exposing it demands hard gating:

- **Never publish `:9222` to a public interface.** It stays `127.0.0.1` in the container;
  only the same-host proxy reaches it via the docker bridge. (`docker_driver.run` already
  publishes **no** ports — keep it that way.)
- **Per-user token, short TTL.** HMAC over `userId` + expiry (≤ 15 min) signed with the
  fleet `WORKER_SECRET`; the proxy verifies before forwarding. One token → one user's
  container. No token / expired / wrong user → 403.
- **TLS only**, via the host's existing ingress (same place the controller is reached).
- **Time-boxed window.** The route is meaningful only while a `NEED_LOGIN` is open; the token
  TTL closes it. (ponytail: TTL is the close mechanism — no separate "revoke" endpoint in v1.)
- **Scope to one target.** Proxy only the order tab's `devtoolsFrontendUrl`, not `/json/new`
  (which would let the holder open arbitrary tabs). ponytail ceiling: v1 may proxy the whole
  `:9222` for simplicity — acceptable ONLY because the token is per-user + minutes-long; tighten
  to a single target id if the window widens.

## Ceilings & upgrade path (ponytail)

- **DNS-rebind / Host-header (must-do, not optional):** Chrome rejects CDP websocket upgrades
  whose `Host:` header isn't `localhost`/an IP (anti-DNS-rebinding). The reverse proxy MUST
  rewrite `Host` → `127.0.0.1:9222` (and `Origin` accordingly) or the DevTools ws silently
  fails to connect. This is the one fiddly bit of (a).
- **UX ceiling:** the built-in DevTools frontend is a developer tool — full inspector chrome
  around a Screencast pane. On a **phone** (the operator onboards from iMessage/Telegram) it's
  clunky. **Upgrade path = option (b):** a tiny mobile-friendly screencast page
  (`Page.startScreencast` → `<canvas>`, mouse/key via `Input.dispatchMouseEvent` /
  `Input.dispatchKeyEvent`). Same proxy/token/security; swap only the page the user lands on.
  Build (b) the moment v1's desktop-DevTools UX proves too rough on mobile.
- **Multi-host:** v1 assumes the proxy runs on the same host as the container (single-host
  fleet, current state). At multi-host, the controller must route `/u/<userId>/` to the right
  host first; the per-host proxy stays the same.
