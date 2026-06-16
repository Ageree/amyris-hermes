#!/bin/bash
# vm-startup.sh — GCE metadata startup-script for the single co-located fleet VM.
#
# Runs as root on every boot (GCE re-runs startup-script each boot; everything
# here is idempotent). Prepares the host so the controller (systemd) can pull the
# fleet image from Artifact Registry and launch per-tenant containers.
#
# It does NOT start the controller — deploy-controller (operator step L6) installs
# the systemd unit + /etc/hermes-fleet/controller.env and starts it. This script
# only lays down the host prerequisites.
#
# Reads one instance-metadata attribute:
#   fleet-ar-host   e.g. "us-central1-docker.pkg.dev" — region AR host for docker auth.
#
# Invariant (Bug C5): the controller runs as user `hermes-fleet` with uid 10001,
# which EQUALS the container's non-root USER (uid 10001 in Dockerfile.fleet). So a
# bind-mount source dir the controller creates under /data/tenants is writable by
# the container without any chown (the controller runs NoNewPrivileges and cannot
# chown anyway).
set -euo pipefail

log() { echo "[vm-startup] $*"; }

# --- metadata: AR host for docker credential helper -----------------------------
META="http://metadata.google.internal/computeMetadata/v1/instance/attributes"
AR_HOST="$(curl -s -H 'Metadata-Flavor: Google' "${META}/fleet-ar-host" || true)"

# --- docker -----------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
    log "installing docker.io"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y --no-install-recommends docker.io
fi
systemctl enable docker
systemctl start docker

# --- gcloud (controller uses `gcloud storage rsync` for GCS state sync) ----------
# Debian GCE images usually ship the CLI; install only if absent.
if ! command -v gcloud &>/dev/null; then
    log "installing google-cloud-cli"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y --no-install-recommends apt-transport-https ca-certificates gnupg curl
    echo "deb https://packages.cloud.google.com/apt cloud-sdk main" \
        > /etc/apt/sources.list.d/google-cloud-sdk.list
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
        | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
    sed -i 's#^deb #deb [signed-by=/usr/share/keyrings/cloud.google.gpg] #' \
        /etc/apt/sources.list.d/google-cloud-sdk.list
    apt-get update -y
    apt-get install -y --no-install-recommends google-cloud-cli
fi

# --- hermes-fleet user (uid 10001, in docker group) ------------------------------
if ! id hermes-fleet &>/dev/null; then
    log "creating hermes-fleet user (uid 10001)"
    groupadd -g 10001 hermes-fleet || true
    useradd -u 10001 -g 10001 -m -s /usr/sbin/nologin hermes-fleet
fi
# Must be able to talk to the docker socket (run/stop containers).
usermod -aG docker hermes-fleet

# --- host dirs --------------------------------------------------------------------
# /data/tenants — per-tenant bind-mount roots, owned by uid 10001 (== container user).
# /opt/hermes-fleet — controller code (deployed in L6).
# /etc/hermes-fleet — controller.env EnvironmentFile (deployed in L6, mode 0600).
mkdir -p /data/tenants /opt/hermes-fleet /etc/hermes-fleet
chown -R hermes-fleet:hermes-fleet /data/tenants /opt/hermes-fleet
# /etc/hermes-fleet holds controller.env (0600). systemd reads EnvironmentFile as
# root, but the controller (running as hermes-fleet) and any `sudo -u hermes-fleet`
# debugging must be able to TRAVERSE this dir — so own it by hermes-fleet, mode 0750
# (no "other" access to the secrets).
chown hermes-fleet:hermes-fleet /etc/hermes-fleet
chmod 0750 /etc/hermes-fleet

# --- docker -> Artifact Registry auth (as hermes-fleet, uses VM SA via metadata) --
# The controller runs `docker pull` as hermes-fleet; the gcloud credential helper
# fetches a token from the attached service account (no interactive login).
if [[ -n "${AR_HOST}" ]]; then
    log "configuring docker auth for ${AR_HOST}"
    sudo -u hermes-fleet HOME=/home/hermes-fleet \
        gcloud auth configure-docker "${AR_HOST}" --quiet || \
        log "WARN: configure-docker failed (controller deploy will retry)"
fi

log "startup complete"
