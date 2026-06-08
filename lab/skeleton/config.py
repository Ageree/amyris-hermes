"""Config for the Phase-1A skeleton webhook bridge.

Reads secrets/paths from the environment. Secrets live in ~/.hermes-savedlab/.env
(chmod 600); load them before constructing Config (e.g. `set -a; . .env; set +a`).
Missing required env vars raise KeyError at startup — fail fast.
"""
from __future__ import annotations

import os


class Config:
    def __init__(self) -> None:
        self.sendblue_key_id = os.environ["SENDBLUE_API_KEY_ID"]
        self.sendblue_secret = os.environ["SENDBLUE_API_SECRET_KEY"]
        # the shared Sendblue number we send FROM
        self.sendblue_from = os.environ["SENDBLUE_FROM_NUMBER"]
        # High-entropy URL path token gating the webhook (primary auth — see app.py).
        # The operator pastes https://<tunnel>/sendblue/inbound/<WEBHOOK_SECRET>
        # into the Sendblue dashboard.
        self.webhook_secret = os.environ["WEBHOOK_SECRET"]
        # The operator's own E.164 iMessage handle: the ONLY inbound number we
        # accept, and the ONLY number we ever reply to (server-side identity).
        self.allowed_user_number = os.environ["ALLOWED_USER_NUMBER"]
        # Concurrency cap around the blocking Hermes subprocess. 1 for single-user P1A.
        self.max_concurrency = int(os.environ.get("MAX_CONCURRENCY", "1"))
        self.hermes_home = os.path.expanduser(
            os.environ.get("HERMES_HOME", "~/.hermes-savedlab")
        )
        self.hermes_dir = os.path.expanduser(
            os.environ.get("HERMES_DIR", "~/hermes-agent")
        )
        self.python_bin = os.path.expanduser(
            os.environ.get("HERMES_PYTHON_BIN", "~/hermes-agent/venv/bin/python")
        )
