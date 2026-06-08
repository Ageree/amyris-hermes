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
        self.hermes_home = os.path.expanduser(
            os.environ.get("HERMES_HOME", "~/.hermes-savedlab")
        )
        self.hermes_dir = os.path.expanduser(
            os.environ.get("HERMES_DIR", "~/hermes-agent")
        )
        self.python_bin = os.path.expanduser(
            os.environ.get("HERMES_PYTHON_BIN", "~/hermes-agent/venv/bin/python")
        )
