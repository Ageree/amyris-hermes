# Phase 1A — Walking Skeleton (single-user, LIVE) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. This is sub-plan P1A of [[2026-06-08-phase1-fleet]]; it proves the pivoted spine live before any fleet/control-plane work.

**Goal:** A live end-to-end loop on the operator's Mac: **iMessage → Sendblue webhook → Python bridge → local Hermes (MiniMax-M3 + real browser) → reply back to the same iMessage.** One hard-wired user, no Convex, no quotas, no container. The agent answers at least one question that *requires a live browser action* (proving the pivot thesis), then replies on the operator's iPhone.

**Architecture:** A small Python FastAPI service (`lab/skeleton/`) receives Sendblue's inbound webhook, runs the already-installed lab Hermes headless (`cli.py -q`) with `HERMES_HOME=~/.hermes-savedlab` (the browser toolset is in Hermes' default `hermes-cli` preset and was e2e-validated 2026-06-08), captures the reply text, and sends it back via Sendblue `POST /send-message`. Public reachability via a `cloudflared` quick tunnel; the operator pastes the tunnel URL into the Sendblue dashboard (webhook config is dashboard-only — confirmed in docs). **This service is a deliberate throwaway spike** — P1C replaces it with the real TS/Convex router.

**Tech Stack:** Python 3.11+ (lab venv), FastAPI + uvicorn, `requests`, `pytest` + `httpx`/`fastapi.testclient`, `cloudflared`. Hermes Agent v0.11.0 (already installed, `~/hermes-agent/venv`), MiniMax-M3.

**Preconditions / working location:**
- Runs in the **lab repo on branch `001-saved-content-agent`** (same place as Phase-0 `lab/resolve.py`, `lab/library.py`, `lab/REPORT.md`). Create code under `lab/skeleton/`.
- `HERMES_HOME=~/.hermes-savedlab`; secrets in `~/.hermes-savedlab/.env` (chmod 600): `SENDBLUE_API_KEY_ID`, `SENDBLUE_API_SECRET_KEY` (⚠ rotate — were in transcript), `MINIMAX_API_KEY`.
- Hermes headless runs as `/Users/saveliy/hermes-agent/venv/bin/python cli.py -q "<msg>"` with `cwd=~/hermes-agent` and `HERMES_HOME` exported (the `hermes` shell alias is not available to subprocesses — see [[hermes-lab-cli-ops]]).

**Sendblue facts (verified from docs 2026-06-08):**
- Base `https://api.sendblue.co/api`; auth headers `sb-api-key-id`, `sb-api-secret-key`.
- Send: `POST /send-message`, JSON body requires `number` (recipient E.164) + `from_number` (our Sendblue number); `content` and/or `media_url`.
- Inbound webhook JSON fields used: `content`, `number` (the end-user / operator iPhone), `from_number`, `is_outbound` (false = inbound — **ignore outbound echoes**), `message_handle` (idempotency key), `media_url`, `opted_out`, `service`, `sendblue_number`.
- **Webhook URL is configured in the dashboard only** (no API) → operator action. A bot cannot DM-initiate iMessage → **the operator must message the number first.**

**Operator inputs required (flagged at the task that needs them):**
- Task 2 live smoke + Task 8: the operator's iPhone number (recipient) and a test iMessage sent to the Sendblue number.
- Task 6: paste the `cloudflared` URL **including the secret path token** (`https://…/sendblue/inbound/<WEBHOOK_SECRET>`) into the Sendblue dashboard webhook field. The webhook is [SECURITY]-gated: the URL path token + a reply-target allowlist (`ALLOWED_USER_NUMBER`) authenticate every request.

---

## Task 1: Sendblue client — outbound send

**Files:**
- Create: `lab/skeleton/sendblue_client.py`
- Test: `lab/skeleton/tests/test_sendblue_client.py`

- [ ] **Step 1: Write the failing test (mocked HTTP)**

```python
# lab/skeleton/tests/test_sendblue_client.py
import json
from unittest.mock import patch, MagicMock
from lab.skeleton.sendblue_client import SendblueClient

def test_send_message_posts_expected_payload_and_headers():
    client = SendblueClient(key_id="kid", secret="sec", from_number="+15550001111")
    with patch("lab.skeleton.sendblue_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"status": "QUEUED"})
        resp = client.send_message(to_number="+15557654321", content="hi")
    assert resp["status"] == "QUEUED"
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.sendblue.co/api/send-message"
    assert kwargs["headers"]["sb-api-key-id"] == "kid"
    assert kwargs["headers"]["sb-api-secret-key"] == "sec"
    body = json.loads(kwargs["data"]) if "data" in kwargs else kwargs["json"]
    assert body["number"] == "+15557654321"
    assert body["from_number"] == "+15550001111"
    assert body["content"] == "hi"

def test_send_message_raises_on_non_2xx():
    client = SendblueClient(key_id="kid", secret="sec", from_number="+15550001111")
    with patch("lab.skeleton.sendblue_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=401, text="unauthorized")
        try:
            client.send_message(to_number="+1555", content="x")
            assert False, "expected error"
        except RuntimeError as e:
            assert "401" in str(e)
```

- [ ] **Step 2: Run test to verify it fails** — `cd <lab-repo> && python -m pytest lab/skeleton/tests/test_sendblue_client.py -v` → FAIL (module not found).

- [ ] **Step 3: Minimal implementation**

```python
# lab/skeleton/sendblue_client.py
"""Thin Sendblue iMessage client (outbound + inbound parsing). Throwaway spike — P1C supersedes."""
from __future__ import annotations
import requests

SENDBLUE_BASE = "https://api.sendblue.co/api"

class SendblueClient:
    def __init__(self, key_id: str, secret: str, from_number: str, timeout: float = 20.0):
        if not key_id or not secret or not from_number:
            raise ValueError("SendblueClient requires key_id, secret, from_number")
        self._headers = {
            "sb-api-key-id": key_id,
            "sb-api-secret-key": secret,
            "Content-Type": "application/json",
        }
        self._from = from_number
        self._timeout = timeout

    def send_message(self, to_number: str, content: str) -> dict:
        if not to_number or not content:
            raise ValueError("to_number and content are required")
        payload = {"number": to_number, "from_number": self._from, "content": content}
        r = requests.post(f"{SENDBLUE_BASE}/send-message", json=payload,
                          headers=self._headers, timeout=self._timeout)
        if not (200 <= r.status_code < 300):
            raise RuntimeError(f"Sendblue send-message failed {r.status_code}: {r.text[:300]}")
        return r.json()
```

- [ ] **Step 4: Run test to verify it passes** — same pytest command → PASS.

- [ ] **Step 5: Commit** — `git add lab/skeleton/sendblue_client.py lab/skeleton/tests/test_sendblue_client.py && git commit -m "feat(skeleton): Sendblue outbound client"`

---

## Task 2: Live outbound smoke (needs operator number)

**Files:** Create: `lab/skeleton/scripts/smoke_send.py`

- [ ] **Step 1: Write the smoke script**

```python
# lab/skeleton/scripts/smoke_send.py
"""One-shot live send to verify Sendblue creds + a real iMessage arrives. Usage:
   set -a; . ~/.hermes-savedlab/.env; set +a
   python lab/skeleton/scripts/smoke_send.py +1<OPERATOR_NUMBER> +1<SENDBLUE_NUMBER>
"""
import os, sys
from lab.skeleton.sendblue_client import SendblueClient

def main():
    to_number, from_number = sys.argv[1], sys.argv[2]
    c = SendblueClient(os.environ["SENDBLUE_API_KEY_ID"], os.environ["SENDBLUE_API_SECRET_KEY"], from_number)
    print(c.send_message(to_number, "Skeleton smoke ✅ — reply to test inbound."))

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run live** (operator provides their iPhone number as recipient and the Sendblue number as `from_number`):
  `set -a; . ~/.hermes-savedlab/.env; set +a; python lab/skeleton/scripts/smoke_send.py +1<iphone> +1<sendblue>`
  Expected: HTTP 200 JSON; the iMessage arrives on the operator's iPhone. **Gate:** if it doesn't arrive, stop and check the number/plan before proceeding. (Note: outbound to a number that never messaged first may be limited by the plan.)

- [ ] **Step 3: Commit** — `git add lab/skeleton/scripts/smoke_send.py && git commit -m "chore(skeleton): live outbound smoke script"`

---

## Task 3: Inbound webhook parser

**Files:**
- Modify: `lab/skeleton/sendblue_client.py` (add `parse_inbound`)
- Test: `lab/skeleton/tests/test_parse_inbound.py`

- [ ] **Step 1: Write the failing test** (payload uses the verbatim Sendblue field names)

```python
# lab/skeleton/tests/test_parse_inbound.py
from lab.skeleton.sendblue_client import parse_inbound, InboundMessage

SAMPLE = {
    "content": "what is the H1 of example.com?",
    "number": "+15557654321",          # end-user (operator iPhone)
    "from_number": "+15557654321",
    "is_outbound": False,
    "message_handle": "abc-123",
    "media_url": "",
    "opted_out": False,
    "service": "iMessage",
    "sendblue_number": "+15550001111",
}

def test_parse_inbound_extracts_fields():
    msg = parse_inbound(SAMPLE)
    assert isinstance(msg, InboundMessage)
    assert msg.text == "what is the H1 of example.com?"
    assert msg.user_number == "+15557654321"
    assert msg.handle == "abc-123"
    assert msg.opted_out is False

def test_parse_inbound_rejects_outbound_echo():
    assert parse_inbound({**SAMPLE, "is_outbound": True}) is None

def test_parse_inbound_rejects_empty_text_and_optout():
    assert parse_inbound({**SAMPLE, "content": ""}) is None
    assert parse_inbound({**SAMPLE, "opted_out": True}) is None
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest lab/skeleton/tests/test_parse_inbound.py -v` → FAIL.

- [ ] **Step 3: Minimal implementation** (append to `sendblue_client.py`)

```python
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class InboundMessage:
    text: str
    user_number: str       # Sendblue `number` — the end-user to reply to
    handle: str            # `message_handle` — idempotency key
    media_url: str
    opted_out: bool

def parse_inbound(payload: dict) -> Optional[InboundMessage]:
    """Validate + normalize a Sendblue inbound webhook. Returns None for anything
    we must ignore (outbound echo, opted-out, empty text). Never trust external data."""
    if not isinstance(payload, dict):
        return None
    if payload.get("is_outbound") is True:
        return None
    if payload.get("opted_out") is True:
        return None
    text = (payload.get("content") or "").strip()
    user_number = (payload.get("number") or "").strip()
    if not text or not user_number:
        return None
    return InboundMessage(
        text=text,
        user_number=user_number,
        handle=str(payload.get("message_handle") or ""),
        media_url=payload.get("media_url") or "",
        opted_out=False,
    )
```

- [ ] **Step 4: Run to verify it passes** → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(skeleton): inbound webhook parser with boundary validation"`

---

## Task 4: Hermes bridge — discover the headless invocation, then wrap it

**Files:**
- Create: `lab/skeleton/hermes_bridge.py`
- Test: `lab/skeleton/tests/test_hermes_bridge.py`

- [ ] **Step 1: DISCOVER the real headless contract (do not assume).** Run once and record the actual stdout shape:
  `HERMES_HOME=~/.hermes-savedlab /Users/saveliy/hermes-agent/venv/bin/python ~/hermes-agent/cli.py -q "Say only the word PONG" 2>/tmp/h.err; echo "---EXIT $?---"; cat /tmp/h.err | tail -5`
  Note: whether the final answer is the entire stdout or needs the last non-empty line; whether `<think>` blocks appear (M3 emits them). Capture findings in a comment at the top of `hermes_bridge.py`.

- [ ] **Step 2: Write the failing test (subprocess mocked)**

```python
# lab/skeleton/tests/test_hermes_bridge.py
from unittest.mock import patch, MagicMock
from lab.skeleton.hermes_bridge import run_hermes

def test_run_hermes_invokes_venv_python_with_home_and_returns_reply():
    fake = MagicMock(returncode=0, stdout="PONG\n", stderr="")
    with patch("lab.skeleton.hermes_bridge.subprocess.run", return_value=fake) as m:
        out = run_hermes("Say PONG", hermes_home="/h", hermes_dir="/hermes",
                         python_bin="/hermes/venv/bin/python")
    assert out == "PONG"
    args, kwargs = m.call_args
    cmd = args[0]
    assert cmd[:3] == ["/hermes/venv/bin/python", "/hermes/cli.py", "-q"]
    assert "Say PONG" in cmd
    assert kwargs["cwd"] == "/hermes"
    assert kwargs["env"]["HERMES_HOME"] == "/h"

def test_run_hermes_strips_think_blocks():
    fake = MagicMock(returncode=0, stdout="<think>reasoning</think>\nThe answer is 42.\n", stderr="")
    with patch("lab.skeleton.hermes_bridge.subprocess.run", return_value=fake):
        out = run_hermes("q", hermes_home="/h", hermes_dir="/d", python_bin="/p")
    assert out == "The answer is 42."

def test_run_hermes_raises_on_nonzero():
    fake = MagicMock(returncode=1, stdout="", stderr="boom")
    with patch("lab.skeleton.hermes_bridge.subprocess.run", return_value=fake):
        try:
            run_hermes("q", hermes_home="/h", hermes_dir="/d", python_bin="/p")
            assert False
        except RuntimeError as e:
            assert "boom" in str(e)
```

- [ ] **Step 3: Run to verify it fails** → FAIL.

- [ ] **Step 4: Minimal implementation** (adjust the stdout extraction per Step 1 findings)

```python
# lab/skeleton/hermes_bridge.py
"""Run the lab Hermes headless and return its reply text.
Step-1 discovery (fill in from real run): final answer = full stdout minus <think> blocks,
trimmed to the last non-empty line if banners appear. The `hermes` shell alias is unavailable
to subprocesses, so we call the venv python + cli.py directly (see hermes-lab-cli-ops)."""
from __future__ import annotations
import os, re, subprocess

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)

def run_hermes(message: str, *, hermes_home: str, hermes_dir: str,
               python_bin: str, timeout: float = 180.0) -> str:
    if not message.strip():
        raise ValueError("empty message")
    env = {**os.environ, "HERMES_HOME": hermes_home}
    proc = subprocess.run(
        [python_bin, f"{hermes_dir}/cli.py", "-q", message],
        cwd=hermes_dir, env=env, capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"hermes exited {proc.returncode}: {proc.stderr[:500]}")
    cleaned = _THINK.sub("", proc.stdout).strip()
    return cleaned or "(no reply)"
```

- [ ] **Step 5: Run to verify it passes** → PASS.
- [ ] **Step 6: Live single-call check** — `python -c "from lab.skeleton.hermes_bridge import run_hermes; print(run_hermes('Reply with exactly: PONG', hermes_home=__import__('os').path.expanduser('~/.hermes-savedlab'), hermes_dir=__import__('os').path.expanduser('~/hermes-agent'), python_bin=__import__('os').path.expanduser('~/hermes-agent/venv/bin/python')))"` → prints `PONG` (or close). Adjust `_THINK`/last-line logic if banners leak.
- [ ] **Step 7: Commit** — `git commit -am "feat(skeleton): headless Hermes bridge"`

---

## Task 5: FastAPI webhook app (wires parse → Hermes → reply)

**Files:**
- Create: `lab/skeleton/app.py`, `lab/skeleton/config.py`
- Test: `lab/skeleton/tests/test_app.py`

- [ ] **Step 1: Write the failing test (TestClient, bridge + sendblue mocked)**

```python
# lab/skeleton/tests/test_app.py
from unittest.mock import patch
from fastapi.testclient import TestClient
from lab.skeleton.app import create_app

TOKEN = "s3cr3t-t0ken"; ALLOWED = "+1555"
PAYLOAD = {"content": "hello", "number": ALLOWED, "is_outbound": False,
           "message_handle": "h1", "opted_out": False}
GOOD_URL = f"/sendblue/inbound/{TOKEN}"

def _client():
    return TestClient(create_app(_FakeCfg()))

class _FakeCfg:
    sendblue_key_id = "k"; sendblue_secret = "s"; sendblue_from = "+1999"
    webhook_secret = TOKEN; allowed_user_number = ALLOWED; max_concurrency = 1
    hermes_home = "/h"; hermes_dir = "/d"; python_bin = "/p"

def test_inbound_runs_hermes_and_replies():
    with patch("app.run_hermes", return_value="hi back") as rh, \
         patch("app.SendblueClient.send_message", return_value={"status":"QUEUED"}) as sm:
        r = _client().post(GOOD_URL, json=PAYLOAD)
    assert r.status_code == 200
    rh.assert_called_once()
    assert sm.call_args.kwargs.get("content") == "hi back" or sm.call_args.args[1] == "hi back"

def test_inbound_ignores_outbound_echo_without_calling_hermes():
    with patch("app.run_hermes") as rh:
        r = _client().post(GOOD_URL, json={**PAYLOAD, "is_outbound": True})
    assert r.status_code == 200
    rh.assert_not_called()

def test_inbound_dedupes_by_handle():
    with patch("app.run_hermes", return_value="x") as rh, \
         patch("app.SendblueClient.send_message", return_value={}):
        c = _client()
        c.post(GOOD_URL, json=PAYLOAD)
        c.post(GOOD_URL, json=PAYLOAD)  # same handle
    assert rh.call_count == 1

# [SECURITY] additional coverage in the real test file: wrong/absent token -> 401/404
# (run_hermes NOT called); non-allowlisted number -> ignored; reply target is ALWAYS
# allowed_user_number; empty/missing handle -> ignored; bounded-LRU eviction; and
# run_hermes dispatched via asyncio.to_thread with timeout=60.
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Minimal implementation**

```python
# lab/skeleton/config.py
import os
class Config:
    def __init__(self):
        self.sendblue_key_id = os.environ["SENDBLUE_API_KEY_ID"]
        self.sendblue_secret = os.environ["SENDBLUE_API_SECRET_KEY"]
        self.sendblue_from   = os.environ["SENDBLUE_FROM_NUMBER"]      # the shared Sendblue number
        # [SECURITY] high-entropy URL path token gating the webhook (primary auth)
        self.webhook_secret  = os.environ["WEBHOOK_SECRET"]
        # [SECURITY] operator's own E.164 handle: the ONLY number we accept inbound from
        # AND the ONLY number we reply to (reply target derived from config, never payload)
        self.allowed_user_number = os.environ["ALLOWED_USER_NUMBER"]
        self.max_concurrency = int(os.environ.get("MAX_CONCURRENCY", "1"))  # cap on blocking Hermes runs
        self.hermes_home = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes-savedlab"))
        self.hermes_dir  = os.path.expanduser("~/hermes-agent")
        self.python_bin  = os.path.expanduser("~/hermes-agent/venv/bin/python")
```

```python
# lab/skeleton/app.py
"""Throwaway single-user webhook bridge: Sendblue inbound -> Hermes -> Sendblue reply.
Idempotency is in-memory (process-local) — fine for the skeleton; P1C uses Convex."""
from __future__ import annotations
import asyncio, hmac, logging
from fastapi import FastAPI, HTTPException, Request
from sendblue_client import SendblueClient, parse_inbound
from hermes_bridge import run_hermes
from _dedup import BoundedDedup            # [SECURITY] bounded LRU (no unbounded set)

log = logging.getLogger("skeleton")

def create_app(cfg) -> FastAPI:
    app = FastAPI()
    client = SendblueClient(cfg.sendblue_key_id, cfg.sendblue_secret, cfg.sendblue_from)
    seen = BoundedDedup()
    sem = asyncio.Semaphore(getattr(cfg, "max_concurrency", 1))  # cap blocking Hermes runs

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # [SECURITY] secret URL path token (constant-time) + reply-target allowlist;
    # run_hermes runs off the event loop (asyncio.to_thread) under a Semaphore.
    @app.post("/sendblue/inbound/{token}")
    async def inbound(token: str, request: Request):
        if not hmac.compare_digest(token, cfg.webhook_secret):
            raise HTTPException(status_code=401)        # 401, NOT 5xx (Sendblue retries 5xx)
        payload = await request.json()
        msg = parse_inbound(payload)
        if msg is None:
            return {"ignored": True}
        if msg.user_number != cfg.allowed_user_number:  # allowlist (server-side identity)
            return {"ignored": True}
        if not msg.handle:                              # empty handle = hard reject
            return {"ignored": True}
        if not seen.add(msg.handle):                    # bounded LRU dedup
            return {"duplicate": True}
        try:
            async with sem:
                reply = await asyncio.to_thread(
                    run_hermes, msg.text, hermes_home=cfg.hermes_home,
                    hermes_dir=cfg.hermes_dir, python_bin=cfg.python_bin, timeout=60)
        except Exception:                               # never 500 back to Sendblue
            log.exception("hermes failed")
            reply = "Sorry — I hit an error processing that. Try again in a moment."
        try:
            # reply target is ALWAYS config-derived, never the inbound payload
            client.send_message(to_number=cfg.allowed_user_number, content=reply[:1800])
        except Exception:
            log.exception("sendblue reply failed")
        return {"ok": True}

    return app
```

- [ ] **Step 4: Run to verify it passes** → `python -m pytest lab/skeleton/tests/test_app.py -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(skeleton): FastAPI inbound webhook (parse->hermes->reply, dedupe)"`

---

## Task 6: Public exposure + Sendblue webhook config (needs operator paste)

**Files:** Create: `lab/skeleton/run.sh`, `lab/skeleton/README.md`

- [ ] **Step 1: Run script**

```bash
# lab/skeleton/run.sh
#!/usr/bin/env bash
set -euo pipefail
export SENDBLUE_FROM_NUMBER="${SENDBLUE_FROM_NUMBER:?set to the shared Sendblue number, e.g. +1...}"
# [SECURITY] required: high-entropy webhook path token + operator's own iMessage handle
export WEBHOOK_SECRET="${WEBHOOK_SECRET:?set to a high-entropy token, e.g. openssl rand -hex 24}"
export ALLOWED_USER_NUMBER="${ALLOWED_USER_NUMBER:?set to the operator's E.164 iMessage number, e.g. +1...}"
export MAX_CONCURRENCY="${MAX_CONCURRENCY:-1}"
set -a; . "$HOME/.hermes-savedlab/.env"; set +a
export HERMES_HOME="$HOME/.hermes-savedlab"
cd "$(git rev-parse --show-toplevel)"
exec /Users/saveliy/hermes-agent/venv/bin/python -m uvicorn lab.skeleton.app:app \
  --factory --host 127.0.0.1 --port 8787
```
(If `app:app --factory` needs a module-level factory, add `app = create_app(Config())` guarded by `if __name__`-style export, or expose `def app(): return create_app(Config())`.)

- [ ] **Step 2: Install deps into the venv** — `~/hermes-agent/venv/bin/pip install fastapi uvicorn requests pytest httpx` (or a `lab/skeleton/requirements.txt`). Verify `/healthz` locally: start `run.sh`, then `curl -s 127.0.0.1:8787/healthz` → `{"ok":true}`.

- [ ] **Step 3: Tunnel** — `cloudflared tunnel --url http://127.0.0.1:8787` (install via `brew install cloudflared` if missing). It prints `https://<random>.trycloudflare.com`. The webhook URL is `https://<random>.trycloudflare.com/sendblue/inbound/<WEBHOOK_SECRET>` — **the secret path token is part of the URL** (it is the primary auth gate; a request to the bare `/sendblue/inbound` 404s, a wrong token 401s).

- [ ] **Step 4: OPERATOR ACTION** — paste that URL **(with the `<WEBHOOK_SECRET>` path token)** into the Sendblue dashboard webhook field (Settings → Webhooks; webhook config is dashboard-only, no API). Document the exact dashboard path in `README.md` once confirmed.

- [ ] **Step 5: Commit** — `git add lab/skeleton/run.sh lab/skeleton/README.md && git commit -m "chore(skeleton): run script + tunnel + webhook setup docs"`

---

## Task 7: Browser action in the loop (proves the pivot)

**Files:** Modify: `lab/skeleton/README.md` (add the canonical browser-test prompt)

- [ ] **Step 1: Verify Hermes uses the browser headlessly for a browser-only question.** Run the bridge directly with a prompt that CANNOT be answered without a live fetch:
  `python -c "from lab.skeleton.hermes_bridge import run_hermes, *paths*; print(run_hermes('Open https://example.com in your browser and reply with the exact text of its H1 heading. Use the browser tool.', ...))"`
  Expected: reply contains **"Example Domain"** (matches the 2026-06-08 e2e). If Hermes answers from memory instead of browsing, sharpen the prompt (explicitly require `browser_navigate`) or pick a URL whose content can't be guessed (e.g. a page with a random nonce you control).
- [ ] **Step 2:** Record the working browser-test prompt in `README.md` as the canonical Task-8 message. Commit.

---

## Task 8: LIVE end-to-end gate (needs operator)

- [ ] **Step 1:** With `run.sh` + tunnel up and the webhook URL pasted (Task 6), the **operator sends an iMessage** from their iPhone to the Sendblue number: *"Open example.com and tell me its H1."*
- [ ] **Step 2:** Observe the loop: webhook hit (FastAPI log) → `parse_inbound` accepts → `run_hermes` drives the browser → reply sent → **iMessage arrives on the iPhone containing "Example Domain".**
- [ ] **Step 3: GATE — go/no-go for P1B+.** Record in `lab/REPORT.md`: round-trip latency, M3 token cost for the turn, and any failures. A green round-trip = the pivoted spine (iMessage ↔ M3 ↔ real browser ↔ iMessage) is proven live. Commit the report update.

---

## Self-review
- **Spec coverage:** proves US-level spine for actions (US4 draft/act loop is exercised minimally as "do a browser action and report"); saved-content (US1/2) and quotas (US5) are explicitly out of P1A scope (P1B/P1D).
- **No placeholders:** every code/test step has real content; the one genuine unknown (exact `cli.py -q` stdout shape) is handled by an explicit discovery step (Task 4 Step 1) before the parser is finalized, not assumed.
- **Boundary validation:** `parse_inbound` rejects outbound echoes, opt-outs, empty text; the app never returns 5xx to Sendblue and truncates replies to 1800 chars.
- **Throwaway discipline:** the Python bridge is labeled a spike; P1C reimplements routing in TS/Convex with durable idempotency and multi-user identity.
- **Type consistency:** `InboundMessage(text, user_number, handle, media_url, opted_out)` used identically across parser, tests, and app.
