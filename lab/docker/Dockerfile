# Saved-content resolver/store core — Phase-1 fleet container base.
# Packages the deterministic skill scripts + their deps (incl. yt-dlp impersonation).
# The full Phase-1 image will layer Hermes Agent on top; this proves the deps build.
FROM python:3.12-slim

# ffmpeg for yt-dlp media muxing; ca-certificates for TLS
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY lab/requirements.txt /app/requirements.txt
# resolver needs yt-dlp WITH curl_cffi so --impersonate works (YouTube/TikTok)
RUN pip install --no-cache-dir -r /app/requirements.txt "yt-dlp[default]" "curl_cffi>=0.11"

COPY lab/ /app/lab/
WORKDIR /app/lab

# Build-time gate: the test suite must pass inside the image (mocked, no network).
RUN python -m pytest -q

# Default: show the resolver CLI help (Phase-1 wraps these in the Hermes runtime).
CMD ["python", "skills/saved-content/scripts/resolve.py", "--help"]
