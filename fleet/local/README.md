# fleet/local — local two-tenant smoke harness

Proves the M6 tenant-isolation invariant **offline, without GCP or real Convex**,
running the **real worker** (`lab/skeleton/worker.py`) unmodified:

> alice's worker only processes alice's messages and replies to alice's address;  
> bob's worker only processes bob's messages and replies to bob's address.  
> ZERO cross-contamination.

## What it proves

| Invariant | How |
|-----------|-----|
| Scoped claim: alice's worker never sees bob's rows | `messages:claimNextForUser` filters by `userId` server-side |
| Correct reply routing: alice's reply goes to alice's address | `replyTarget` comes from the claimed row, never from worker config |
| Cross-contamination detection: a bug is caught, not hidden | `assert_no_cross_contamination()` fails on a mismatched route |
| The pass is **not vacuous** | the assertion FAILS if either tenant produced zero replies, and a unit test feeds a deliberately cross-routed reply and asserts rejection |

## Files

| File | Purpose |
|------|---------|
| `mock_outbound.py` | Stdlib HTTP server — **fake Convex** (`/api/mutation`, `/api/query`) + **fake MiniMax chat** (`/v1/chat/completions`) + outbound reply sink + routing validator |
| `seed.py` | Enqueues one message per tenant, polls `/status`, triggers the assertion, exits with the routing result |
| `fake_controller.py` | No-op stub for the real fleet controller (`fleet/controller/`) |
| `docker-compose.yml` | Two-tenant compose harness (daemon-gated) |
| `.env.example` | Placeholder env vars — copy to `.env` for a live run |
| `test_harness_logic.py` | Network-free unit tests — run WITHOUT docker |

## How it actually works (the protocols matter)

The real worker uses `lab/skeleton/convex_client.py`, which speaks the **Convex HTTP
API** — not a bespoke REST API. `mock_outbound` therefore implements:

- `POST /api/mutation` and `POST /api/query` with body `{"path","args","format":"json"}`,
  returning the Convex success envelope `{"status":"success","value":...}`
  (errors come back as HTTP 200 with `{"status":"error","errorMessage":...}`).
  It dispatches by the `path` field to: `messages:claimNextForUser`,
  `messages:complete`, `messages:fail`, `fleet:heartbeat`, `messages:recentForUser`,
  `messages:enqueue` (seed helper); any other path returns `null` (success) so
  nothing 404s.

Because the offline image has no Hermes, the worker generates a reply via the
**fast lane** pointed at `mock_outbound`:

- compose sets `FAST_LANE_ENABLED=1`, `MINIMAX_API_KEY=mock-key`,
  `MINIMAX_BASE_URL=http://mock_outbound:8800/v1`, `MINIMAX_MODEL=MiniMax-M3`,
  `STREAMING_ENABLED=0`.
- `mock_outbound` serves `POST /v1/chat/completions` returning a plain,
  URL-free, refusal-free, marker-free body `{"choices":[{"message":{"content":"ok, handled."}}]}`,
  so `fast_reply` **returns** the text (does not defer) and the worker calls
  `messages:complete`. A unit test verifies this body is accepted by the *real*
  `fast_lane.fast_reply`.

## Quick start (no docker required)

The harness logic is fully tested without a docker daemon:

```bash
cd /path/to/repo-root           # e.g. /Users/saveliy/Documents/Amyris
python3 -m pytest fleet/local/test_harness_logic.py -q
```

Expected:
```
25 passed in ~4s
```

## Docker compose run (requires docker daemon)

```bash
cd fleet/local

# Build + run; exits with seed's exit code (0 = pass)
docker compose up --build --abort-on-container-exit --exit-code-from seed

# Verify the acceptance criterion — BOTH lines must appear:
docker compose logs mock_outbound | grep -E 'alice->alice|bob->bob'

# Clean up
docker compose down -v
```

## Env vars

Copy `.env.example` to `.env` in this directory:

```bash
cp .env.example .env
chmod 600 .env
# For offline mock mode the placeholder values work as-is.
```

For **offline / mock mode** (the default) no real credentials are needed —
workers call `mock_outbound` instead of real Convex/Sendblue/MiniMax.

## Architecture

```
seed ──/api/mutation messages:enqueue──► mock_outbound  (fake Convex + fake model + sink)
                                              │
                       ┌──────────────────────┼──────────────────────┐
                       ▼                       │                       ▼
                 worker_alice                  │                  worker_bob
                 USER_ID=u_alice               │                  USER_ID=u_bob
                       │                       │                       │
   claimNextForUser(u_alice) → alice's row     │   claimNextForUser(u_bob) → bob's row
                       │                       │                       │
   fast lane → /v1/chat/completions → "ok, handled."  (same for bob)   │
                       │                       │                       │
   messages:complete ──┴───────────────────────┴───────────────────────┘
                       │
                       ▼
   mock_outbound records each reply tagged by the ROW's owner + target,
   logs the routing line, and validates on /shutdown:
                       │
                  alice->alice   ← acceptance grep
                  bob->bob       ← acceptance grep
                  assertion PASS (alice=1 bob=1 cross=0)
```

## Negative / non-vacuous proof

`test_harness_logic.py::TestRoutingValidation::test_cross_routed_reply_is_rejected`
constructs a row owned by `u_alice` but addressed to bob's number (the exact shape
a routing bug produces), completes it, and asserts the validator returns
`passed=False` with a `CROSS-CONTAMINATION` line. Plus `test_vacuous_run_fails` and
`test_only_one_tenant_replies_fails` guarantee an empty / half-empty reply set
FAILS — so a green compose run can never be a false pass.

## Notes

- **Daemon-gated**: the compose-up leg needs a running docker daemon. The unit test
  leg (`test_harness_logic.py`) runs anywhere Python 3.8+ is available.
- `mock_outbound.py` and `seed.py` use **stdlib only** — no pip installs.
- `fake_controller.py` is a no-op stub; the real controller lives in `fleet/controller/`.
- Workers use `INSTALL_HERMES=0` in compose (offline build, no Hermes clone).
  Production Cloud Build passes `INSTALL_HERMES=1`.
- No real secrets — secrets arrive via env; `.env` is gitignored.
