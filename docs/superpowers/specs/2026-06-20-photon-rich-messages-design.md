# Rich iMessage via Photon + Telegram polls — design

**Date:** 2026-06-20
**Status:** draft for operator review
**Owner:** Hermes Fleet (saved-content assistant)

## Goal

Give the assistant **rich messaging** on both channels, keeping the current
product architecture (Convex durable queue → worker → bridge → `hermes chat`
headless brain → product's own channel layer). Operator-locked scope.

## Scope (locked 2026-06-20)

Spectrum Cloud's SDK (the only real send transport — gRPC, no plain HTTP) and the
Hermes v0.17.0 Photon sidecar expose exactly these. The marketing page lists more
(polls/contacts/carousels/effects/mini-apps) but **they are not in the SDK** — we
do not promise them.

**iMessage (via Photon), buildable today:**

| Capability | Sidecar route | Sendblue had it? |
|---|---|---|
| text + light markdown | `POST /send` | yes (text) |
| photo / file attachment | `POST /send-attachment` | partial (media_url, unused) |
| voice note bubble | `POST /send-attachment` (`voice`) | no |
| reaction / tapback (+remove) | `POST /react` / `/unreact` | no |
| typing indicator | `POST /typing` | yes |

**Telegram parity** (Bot API, already partly built): text/markdown→HTML (done),
photo (`sendPhoto`), file (`sendDocument`), voice (`sendVoice`), reaction
(`setMessageReaction`), **native poll (`sendPoll`)** — the one feature TG has that
iMessage doesn't.

**Out of scope (SDK gap):** polls/contacts/carousels/effects/backgrounds/
mini-apps on iMessage. iMessage poll degrades to a text list.

## Non-negotiables kept

- Convex queue / multi-tenancy / billing / fast-lane / conversation-memory all stay
  on the inbound + claim path. Photon only swaps the iMessage **transport**.
- The brain stays a headless `hermes chat --query=` returning a **flat string**.
  No bridge change. (Rich is a channel-layer parsing convention — see §Rich contract.)
- Sendblue stays installed as a **kill-switch** (`IMESSAGE_PROVIDER=sendblue|photon`,
  default `photon` once cut over). Same pattern as the Lane-B browser kill-switch.

## Architecture

```
                Spectrum Cloud (gRPC, project line)
                          │  (one project stream, all senders)
                ┌─────────▼──────────┐
                │  Photon sidecar    │  REUSED from Hermes v0.17.0 (MIT):
                │  (Node + spectrum) │  plugins/platforms/photon/sidecar/index.mjs
                │  loopback HTTP     │  /inbound (NDJSON) /send /send-attachment
                │  bearer-token      │  /react /unreact /typing /healthz
                └───┬────────────▲───┘
       inbound NDJSON│            │ outbound loopback POST (bearer)
          ┌──────────▼──┐      ┌──┴───────────────┐
          │ inbound      │      │ PhotonChannel    │  (Python, channel layer)
          │ consumer     │      │ kind="imessage"  │  satisfies Channel Protocol
          │ (singleton)  │      └──▲───────────────┘
          └──────┬───────┘         │ worker.registry.get("imessage")
   Convex enqueue│                 │
   {channel=imessage,              │
    replyTarget=sender,            │
    userId=binding}                │
          ┌──────▼─────────────────┴────────┐
          │  EXISTING: Convex queue → claim  │
          │  → worker → bridge → hermes chat │
          └──────────────────────────────────┘
```

### Components

1. **Photon sidecar (reused).** Vendor `plugins/platforms/photon/sidecar/`
   (index.mjs + package.json + the mixed-attachment patch) into the repo
   (`lab/photon-sidecar/`) and `bun/npm install` (`spectrum-ts@3.1.0`). It holds the
   project gRPC stream and exposes the loopback control API. We do **not** reimplement
   gRPC. License: MIT (upstream NousResearch).

2. **Inbound consumer (new, singleton).** A small Python loop (modeled on Hermes
   `adapter.py::_inbound_loop`): read sidecar `GET /inbound` NDJSON, dedup
   (gRPC is at-least-once), map **sender phone → product user** via the existing
   `channelBindings`, and `enqueue` into Convex (`channel="imessage"`,
   `replyTarget=<sender>`, `userId=<bound>`). Unknown sender → onboarding/ignore per
   policy. One sidecar + one consumer per **project** (not per tenant — the project
   stream already carries every sender).

3. **PhotonChannel (new, Python).** Implements the `Channel` Protocol
   (`send_message`, `send_typing`, `split`, `render`) + a new `send_rich` (see below):
   - `send_message(addr, text)` → `POST /send`
   - `send_typing(addr, …)` → `POST /typing`
   - `send_rich(addr, part)` → `/send-attachment` (photo/file/voice) or `/react`
   - manages the sidecar process lifecycle (spawn + `/healthz` + reap-stale-on-port),
     reusing adapter.py's proven approach.
   - `from_config` builds `channels["imessage"]=PhotonChannel(...)` when
     `IMESSAGE_PROVIDER=photon` + creds present, else `SendblueChannel`.

4. **Telegram channel (extend existing).** Add `sendPhoto`/`sendDocument`/`sendVoice`/
   `sendPoll`/`setMessageReaction` to `telegram_client.py`; map rich parts in
   `telegram_channel.py`. Text/markdown→HTML already works.

### Rich contract (the only "seam" change — channel-layer only)

The brain returns a flat string. The channel layer parses it into ordered parts:

```
RichPart = text(str)
         | image(url|path) | file(url|path) | voice(url|path)
         | reaction(emoji, target=last_inbound)
         | poll(question, [options])        # TG only; iMessage → text list
```

- **Parser** (`channels/rich.py`, shared): extracts from the reply —
  markdown image `![](url)` / bare image URL → `image`; a fenced ```` ```poll ````
  block → `poll`; a leading `[[react:❤️]]` token → `reaction`; everything else → `text`.
- Each channel renders the parts **it supports**; unsupported degrade
  (iMessage poll → numbered text list; TG keeps native poll).
- The assistant is **taught the markup** via a SOUL/skill note (so it knows it may
  emit `[[react:…]]`, a poll fence, or an image URL). No new model capability —
  Hermes already emits image URLs and markdown.
- `ponytail:` keep the parser tiny + regex-based; the ceiling is "directive
  collisions in normal prose" → the tokens (`[[react:]]`, ```` ```poll ````) are
  chosen to not appear in ordinary replies; revisit if false positives show up.

## Inbound mapping & multi-tenancy

- The project gRPC stream delivers every sender's messages to the single sidecar.
- The consumer resolves `sender phone → userId` from `channelBindings` (already the
  source of truth, set at the authenticated web onboarding). This preserves
  per-tenant routing, quotas, billing, fast-lane, memory unchanged.
- Allocation model (operator picks tier): **Business = one project number** for all
  users (matches today's single Sendblue number, simplest onboarding) vs **Free/Pro =
  pooled per-user numbers** (each user texts a different number → binding keys on the
  assigned line). Recommend **Business / single number** for parity.

## Deployment topology

- The sidecar + inbound consumer are a **new singleton service**, co-located with the
  shared bridge worker (the process that already owns iMessage replies). Outbound: any
  worker replying on iMessage POSTs to the sidecar loopback — so the sidecar must be
  reachable by the reply-side worker(s). For the current prod (one shared bridge
  worker), co-locate sidecar + consumer + that worker on one host. Per-user fleet
  containers reply via the same sidecar loopback (host-internal) — confirmed in
  writing-plans.
- Runtime needs **Node ≥18.17** (sidecar) alongside Python.
- Sidecar host needs **ffmpeg** on PATH for non-m4a voice notes (mp3/wav → m4a/aac); m4a/aac inputs need none. (Fleet image ships it via `Dockerfile.fleet`.)

## Cutover & rollback

1. Provision a Photon iMessage line (operator; `lines: []` today).
2. Deploy sidecar + consumer (Sendblue still primary).
3. Flip a **test** binding to Photon, prove inbound→queue→reply + each rich type.
4. Re-point onboarding number (web shows the Photon line; new bindings = Photon).
5. Migrate the operator binding Sendblue→Photon; set `IMESSAGE_PROVIDER=photon`.
6. **Rollback:** `IMESSAGE_PROVIDER=sendblue` + re-point binding → Sendblue path
   (untouched) resumes. Sidecar stays installed, idle.

## Operator prerequisites (external, paid)

- **iMessage line not yet provisioned** (`GET /projects/{id}/lines/` → `[]`). Needs a
  line via the dashboard or `lines/route` (may allocate a paid number — operator-gated).
- **Pricing** not in docs — confirm tier/cost in app.photon.codes before prod flip.
- `PHOTON_PROJECT_ID` / `PHOTON_PROJECT_SECRET` stored (chmod 600); **rotate** (pasted
  in chat).

## Testing

- Unit: rich parser (each part type, degradation, no false-positive on prose);
  PhotonChannel maps each part → correct sidecar route (faked HTTP); from_config
  provider switch; inbound consumer phone→user mapping + dedup.
- Contract: feed the sidecar's real `/inbound` event shape into the consumer
  (producer↔consumer seam, per repo gotcha).
- Live e2e (after line provisioned): send each rich type to a test number, verify
  on a real device; reaction targets the right message; TG poll renders natively.
- Keep Sendblue suite green (kill-switch path intact).

## Risks

- **SDK capability drift** — polls/contacts/etc. may land later; parser is additive.
- **gRPC at-least-once** — dedup in the consumer (msg id), as Hermes does.
- **Sidecar lifecycle** — orphan-on-port; reuse adapter.py reap logic + `/healthz`.
- **Cost** — unknown Photon pricing; gated behind operator confirmation.
- **Number change** — existing Sendblue users would need to re-text the new line;
  for a single real user (operator) this is trivial; document for future users.

## Phases (for writing-plans)

P1 sidecar vendored + installs + `/healthz` green locally.
P2 PhotonChannel + from_config switch + rich parser + unit tests.
P3 inbound consumer + Convex enqueue + phone→user mapping + contract test.
P4 Telegram rich (photo/file/voice/reaction/poll) + tests.
P5 SOUL/skill markup note; line provisioning; live e2e; operator cutover; rotate keys.
