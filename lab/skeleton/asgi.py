"""ASGI entrypoint for uvicorn.

Run via ./run.sh, which adds this directory to uvicorn's --app-dir so the
bare-module imports (matching the lab's test convention) resolve. Builds the
app from environment-backed Config at import time, so missing required env
vars fail fast with a clear KeyError naming the variable.
"""
from app import create_app
from config import Config

app = create_app(Config())
