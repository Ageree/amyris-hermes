# Photon sidecar — run & contract (vendored from Hermes v0.17.0, MIT)

> **LOCAL PATCH — diverges from the verbatim Hermes copy.** The
> `/send-attachment` route now wraps an http(s) `path` in `new URL(path)` before
> calling `attachment()`/`voice()` (`index.mjs`, the `src = /^https?:\/\//i…`
> line just above the builder). **Why:** spectrum-ts treats a *string* `path` as
> a LOCAL file (`stat()`) and only fetches over the network when handed a `URL`
> object — so without this, remote image/file/voice URLs silently fail. This is
> the ONLY intentional edit to the otherwise-upstream sidecar; do not re-vendor
> over it without re-applying this one line.

Vendored from `plugins/platforms/photon/sidecar/` (NousResearch, MIT) — with the
single LOCAL PATCH noted above; otherwise verbatim.
This is the **iMessage rich transport**: a Node process that holds the Photon
Spectrum gRPC project stream and exposes a **loopback-only** HTTP control API.
Python (`PhotonChannel` for outbound, the inbound consumer for `/inbound`) talks
to it over `http://127.0.0.1:<port>` with a bearer token header. We do **not**
reimplement gRPC — `spectrum-ts` has no Python SDK. See `index.mjs` for source of
truth; this doc is the contract other product code is written against.

> Treat `index.mjs` / the patch as upstream — wrap behaviour from Python instead
> (matches `adapter.py`'s isolation of all outbound behind one `_sidecar_send`
> helper). The sole sanctioned exception is the LOCAL PATCH documented above (the
> http(s) `new URL(path)` line); any further edits should be pushed upstream, not
> forked here.

## Requirements

- **Node ≥ 18.17** (declared in `package.json` `engines`). Verified here on v22.
- `npm install` (vendored `package-lock.json` pins `spectrum-ts@3.1.0`; a
  `postinstall` runs `patch-spectrum-mixed-attachments.mjs`, which patches the
  installed SDK so mixed text+attachment sends work — the patch self-heals on
  every install and is also re-applied at boot by `index.mjs`).
- `node_modules` is gitignored (`lab/photon-sidecar/node_modules`); run
  `npm install` after checkout.

## Environment variables (read directly by `index.mjs`)

**Required** — boot aborts (exit 2) if any of these three are unset:

| Var | Meaning |
|---|---|
| `PHOTON_PROJECT_ID` | Spectrum project id (`spectrumProjectId`). From the operator's stored Photon creds — **never hardcode**. |
| `PHOTON_PROJECT_SECRET` | Spectrum project secret. From env / `WorkerConfig`, never a literal. |
| `PHOTON_SIDECAR_TOKEN` | Shared bearer the loopback HTTP API requires on **every** request via `X-Hermes-Sidecar-Token`. Generate per run, e.g. `openssl rand -hex 16`. |

**Optional:**

| Var | Default | Meaning |
|---|---|---|
| `PHOTON_SIDECAR_PORT` | `8789` | Loopback TCP port the HTTP API listens on. |
| `PHOTON_SIDECAR_BIND` | `127.0.0.1` | Bind address. Keep loopback. |
| `PHOTON_SIDECAR_WATCH_STDIN` | unset | `"1"` ⇒ exit when stdin hits EOF (parent-death detection; the Python supervisor holds the stdin pipe so a dead supervisor can't orphan the sidecar squatting the port). |
| `PHOTON_MAX_INLINE_ATTACHMENT_BYTES` | `20971520` (20 MiB) | Inbound binary above this is forwarded as metadata only (no base64 `data`). |
| `PHOTON_TELEMETRY` | off | `1\|true\|yes\|on` enables Spectrum SDK telemetry. |

## Launch

The Python `PhotonChannel` supervises this process (spawn + `/healthz` poll +
reap-stale-on-port + restart on crash), passing `PHOTON_SIDECAR_WATCH_STDIN=1`.
Standalone, for debugging only (no live line provisioned yet — gRPC connect needs
a real Photon project + an iMessage line, which is P5):

```bash
cd lab/photon-sidecar
PHOTON_PROJECT_ID=...        \
PHOTON_PROJECT_SECRET=...    \
PHOTON_SIDECAR_PORT=8789     \
PHOTON_SIDECAR_TOKEN=$(openssl rand -hex 16) \
node index.mjs
# stderr: "photon-sidecar: listening on 127.0.0.1:8789"
```

Logs go to **stderr**; the supervisor restarts on a fatal exit. On SIGINT/SIGTERM
the sidecar calls `app.stop()` (3s graceful) before exiting.

## HTTP control API (contract for PhotonChannel + the inbound consumer)

Loopback only. **Every** request must carry `X-Hermes-Sidecar-Token: <token>` or
gets `401 {"ok":false,"error":"unauthorized"}`. All POST bodies are JSON. Success
is `200 {"ok":true, ...}`; client errors are `400 {"ok":false,"error":"<msg>"}`;
server faults are `500 {"ok":false,"error":"internal sidecar error"}` (generic on
purpose — no stack leak). Non-POST to a non-`/inbound` route ⇒ `405`. Request
bodies are capped at 2 MiB.

| Method · Route | Request body (JSON) | Success response |
|---|---|---|
| `GET /inbound` | — (long-lived stream; **one consumer at a time**, a new connection supersedes the old) | `200`, `Content-Type: application/x-ndjson`; one JSON event per line; **blank line = heartbeat** (~25 s). |
| `POST /healthz` | `{}` | `{"ok":true}` |
| `POST /send` | `{"spaceId": str, "text": str, "format": "text"\|"markdown"}` (`format` default `"text"`) | `{"ok":true, "messageId": str\|null}` |
| `POST /send-attachment` | `{"spaceId": str, "path": str, "name": str\|null, "mimeType": str\|null, "caption": str\|null, "kind": "attachment"\|"voice"}` | `{"ok":true, "messageId": str\|null}` |
| `POST /react` | `{"spaceId": str, "messageId": str, "emoji": str}` | `{"ok":true, "reactionId": str\|null}` |
| `POST /unreact` | `{"spaceId": str, "messageId": str, "reactionId": str\|null}` | `{"ok":true}` |
| `POST /typing` | `{"spaceId": str, "state": "start"\|"stop"}` (`state` default `"start"`) | `{"ok":true}` |
| `POST /shutdown` | `{}` | `{"ok":true}`, then the process SIGTERMs itself. |

### Field notes (drawn from `index.mjs`)

- **`spaceId`** addresses the conversation. It may be an opaque inbound space id, a
  bare E.164 phone (`+1...`, addresses a DM), or a Photon DM chat guid
  (`any;-;+1...`). The sidecar resolves/caches it (`resolveSpace`).
- **`/send` `format`**: `"text"` ⇒ `spectrumText`; `"markdown"` ⇒ `spectrumMarkdown`
  (iMessage renders markdown natively; degrades to plain text elsewhere). Anything
  else ⇒ `400 "format must be text or markdown"`.
- **`/send-attachment`**: `path` is a **local file path** the sidecar reads;
  `kind:"voice"` builds a voice-note bubble, anything else a normal attachment.
  `name`/`mimeType` override the extension-inferred values only when non-empty.
  A `caption` is delivered as a **separate text bubble after** the media (caption
  failure is logged, not fatal — the attachment still counts as sent).
- **`/react`**: `messageId` is the **target inbound message** to tapback. One
  tapback per (space,message) — a new `/react` overwrites the slot. `400` if the
  message can't be found or the platform doesn't support reactions.
- **`/unreact`**: removes the tapback. Pass `reactionId` (from the `/react`
  response) for restart-recovery when the live handle was lost. A stale/missing
  tapback is a **soft 400**, not a sidecar bug (it self-heals on the next `/react`).
- **`/typing`**: `state` must be `"start"` or `"stop"`.

### `/inbound` NDJSON event shape (what the inbound consumer parses)

One JSON object per line (blank line = heartbeat — skip it). gRPC is
**at-least-once**, so the consumer **must dedup on `messageId`**. Only inbound
messages are forwarded (the sidecar drops our own outbound echoes).

```jsonc
{
  "messageId": "string|null",
  "platform": "iMessage",
  "space": { "id": "string|null", "type": "dm|group", "phone": "string|null" },
  "sender": { "id": "string|null" },        // the phone → product-user mapping key
  "content": <content>,                       // see below
  "timestamp": "ISO-8601 string|null"
}
```

`content` is one of:

```jsonc
{ "type": "text", "text": "string" }
{ "type": "attachment", "id": str|null, "name": str|null, "mimeType": str|null,
  "size": int|null, "data": "base64", "encoding": "base64" }   // data omitted if over cap / unreadable
{ "type": "voice", ...attachment fields..., "duration": number? }
{ "type": "group", "items": [ { "id": str|null, "content": <content> }, ... ] }
{ "type": "reaction", "emoji": "string", "targetMessageId": str|null,
  "targetDirection": "inbound|outbound|null" }                 // gate "reaction to MY message"
{ "type": "unknown" }
```

> When replying on iMessage, a worker POSTs to this sidecar's loopback — so the
> sidecar must be reachable by every reply-side worker (co-located with the shared
> bridge worker; fleet containers reply via the same host-internal loopback).
