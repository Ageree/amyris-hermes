# fleet/local — local two-tenant smoke harness

Proves the M6 tenant-isolation invariant **offline, without GCP or real Convex**:

> alice's worker only processes alice's messages and replies to alice's address;  
> bob's worker only processes bob's messages and replies to bob's address.  
> ZERO cross-contamination.

## What it proves

| Invariant | How |
|-----------|-----|
| Scoped claim: alice's worker never sees bob's rows | `claimNextForUser` filters by `userId` server-side |
| Correct reply routing: alice's reply goes to alice's address | `replyTarget` is set by the row, never by the worker's config |
| Cross-contamination detection: a bug is caught and logged | `assert_no_cross_contamination()` fails loudly |

## Files

| File | Purpose |
|------|---------|
| `mock_outbound.py` | Stdlib HTTP server — fake Convex queue + outbound sink |
| `seed.py` | Enqueues one message per tenant, waits for replies, asserts routing |
| `fake_controller.py` | No-op stub for the real fleet controller (fleet/controller/) |
| `docker-compose.yml` | Two-tenant compose harness (daemon-gated) |
| `.env.example` | Placeholder env vars — copy to `.env` for a live run |
| `test_harness_logic.py` | Network-free unit tests — run WITHOUT docker |

## Quick start (no docker required)

The routing logic is fully tested without a docker daemon:

```bash
cd /path/to/repo-root
python3 -m pytest fleet/local/test_harness_logic.py -q
```

Expected output:
```
................
16 passed in 0.??s
```

## Docker compose run (requires docker daemon)

```bash
# Build the fleet image (repo root is the build context)
docker compose -f fleet/local/docker-compose.yml build

# Run the smoke test; exits with seed's exit code (0 = pass)
docker compose -f fleet/local/docker-compose.yml up \
    --abort-on-container-exit --exit-code-from seed

# Verify the acceptance criterion — both log lines must appear:
docker compose -f fleet/local/docker-compose.yml logs mock_outbound \
    | grep -E 'alice->alice|bob->bob'
```

## Env vars

Copy `.env.example` to `.env` in this directory:

```bash
cp fleet/local/.env.example fleet/local/.env
chmod 600 fleet/local/.env
# Edit fleet/local/.env — for offline mock mode the placeholder values work as-is
```

For **offline / mock mode** (the default) no real credentials are needed.
Workers call `mock_outbound` instead of real Convex/Sendblue.

For a **live run** set real `SENDBLUE_*` and `MINIMAX_API_KEY` values and
remove `FAST_LANE_ENABLED: "0"` from the compose file.

## Architecture

```
seed ──enqueue──► mock_outbound (fake Convex)
                       │
              ┌────────┼────────┐
              ▼        │        ▼
         worker_alice  │   worker_bob
         USER_ID=u_alice│  USER_ID=u_bob
              │        │        │
        claim alice row│  claim bob row
              │        │        │
        complete ──────┼────────┘
              │        │
              ▼        ▼
         mock_outbound records reply (tagged by user_id)
              │
              ▼
         assert_no_cross_contamination()
              │
          alice->alice  ← acceptance grep
          bob->bob      ← acceptance grep
```

## Notes

- This harness is **daemon-gated**: the compose-up leg requires a running docker daemon.  
  The unit test leg (`test_harness_logic.py`) runs anywhere Python 3.8+ is available.
- `mock_outbound.py` and `seed.py` use **stdlib only** — no pip installs.
- The `fake_controller.py` is a no-op stub; the real controller lives in `fleet/controller/`.
- Workers use `INSTALL_HERMES=0` in compose (offline build) so no Hermes clone is needed.  
  Production Cloud Build passes `INSTALL_HERMES=1`.
