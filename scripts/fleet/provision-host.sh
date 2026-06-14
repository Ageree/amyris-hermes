#!/usr/bin/env bash
# provision-host.sh — GCP host provisioning for the Hermes fleet (M6).
#
# OPERATOR-RUN ONLY. Requires:
#   - A funded GCP project with billing enabled.
#   - gcloud CLI installed and authenticated (gcloud auth login / ADC).
#   - Run with --apply to actually create resources; omit it (or use --dry-run)
#     for a safe preview of the commands that WOULD run.
#
# Idempotent: every create is guarded by a `describe ... || create ...` check.
# Every gcloud call explicitly passes --project=$PROJECT to avoid accidentally
# operating on the gcloud default project (which may differ).
#
# Usage:
#   ./provision-host.sh [--project PROJECT] [--region REGION] [--zone ZONE]
#                       [--apply | --dry-run]
#
# Environment overrides (lowest priority; flags take precedence):
#   PROJECT, REGION, ZONE
#
# Exit codes:
#   0 — success (or dry-run complete)
#   1 — precondition failure or fatal error

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PROJECT="${PROJECT:-hermes-saved-content-lab}"
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-us-central1-a}"
DRY_RUN=true   # safe by default; --apply overrides

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)   PROJECT="$2"; shift 2 ;;
        --region)    REGION="$2";  shift 2 ;;
        --zone)      ZONE="$2";    shift 2 ;;
        --apply)     DRY_RUN=false; shift  ;;
        --dry-run)   DRY_RUN=true;  shift  ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            echo "Usage: $0 [--project P] [--region R] [--zone Z] [--apply | --dry-run]" >&2
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Coloured log helpers (safe even without a terminal)
_info()  { echo "[INFO]  $*"; }
_warn()  { echo "[WARN]  $*" >&2; }
_error() { echo "[ERROR] $*" >&2; }
_abort() { _error "$*"; exit 1; }

# run_cmd — in --apply mode: execute. In --dry-run mode: print only.
run_cmd() {
    if [[ "$DRY_RUN" == true ]]; then
        echo "  [DRY-RUN] $*"
    else
        "$@"
    fi
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "  Hermes Fleet — GCP host provisioner"
echo "  PROJECT = $PROJECT"
echo "  REGION  = $REGION"
echo "  ZONE    = $ZONE"
if [[ "$DRY_RUN" == true ]]; then
    echo "  MODE    = DRY-RUN (no changes will be made)"
else
    echo "  MODE    = APPLY (resources will be created)"
fi
echo "======================================================================"
echo ""

# ---------------------------------------------------------------------------
# Step 0: Preconditions
# ---------------------------------------------------------------------------
_info "Checking preconditions..."

# gcloud installed?
if ! command -v gcloud &>/dev/null; then
    _abort "gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install"
fi
_info "gcloud found: $(gcloud version 2>/dev/null | head -1)"

# An account must be active
if ! gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>/dev/null | grep -q '@'; then
    _abort "No active gcloud account found. Run: gcloud auth login"
fi
ACTIVE_ACCOUNT="$(gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>/dev/null | head -1)"
_info "Active account: $ACTIVE_ACCOUNT"

# Warn if the caller's gcloud default project differs from $PROJECT (easy foot-gun)
DEFAULT_PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
if [[ "$DEFAULT_PROJECT" != "$PROJECT" ]]; then
    _warn "gcloud default project is '$DEFAULT_PROJECT'; provisioning into '$PROJECT' instead."
    _warn "Every command below passes --project=$PROJECT explicitly."
fi

echo ""

# ---------------------------------------------------------------------------
# Step 1: Enable required APIs
# ---------------------------------------------------------------------------
_info "Step 1: Enabling required GCP APIs on project $PROJECT ..."
run_cmd gcloud services enable \
    compute.googleapis.com \
    secretmanager.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    --project="$PROJECT"

echo ""

# ---------------------------------------------------------------------------
# Step 2: Artifact Registry — docker repo `hermes`
# ---------------------------------------------------------------------------
_info "Step 2: Artifact Registry repo 'hermes' (docker, $REGION) ..."
if [[ "$DRY_RUN" == true ]]; then
    echo "  [DRY-RUN] gcloud artifacts repositories describe hermes --location=$REGION --project=$PROJECT"
    echo "  [DRY-RUN]   || gcloud artifacts repositories create hermes \\"
    echo "  [DRY-RUN]       --repository-format=docker \\"
    echo "  [DRY-RUN]       --location=$REGION \\"
    echo "  [DRY-RUN]       --description='Hermes fleet container images' \\"
    echo "  [DRY-RUN]       --project=$PROJECT"
else
    gcloud artifacts repositories describe hermes \
        --location="$REGION" \
        --project="$PROJECT" &>/dev/null \
    || gcloud artifacts repositories create hermes \
        --repository-format=docker \
        --location="$REGION" \
        --description="Hermes fleet container images" \
        --project="$PROJECT"
fi

echo ""

# ---------------------------------------------------------------------------
# Step 3: GCS bucket for tenant state
# ---------------------------------------------------------------------------
BUCKET="gs://hermes-fleet-state"
_info "Step 3: GCS bucket $BUCKET (uniform access) ..."
if [[ "$DRY_RUN" == true ]]; then
    echo "  [DRY-RUN] gcloud storage buckets describe $BUCKET --project=$PROJECT"
    echo "  [DRY-RUN]   || gcloud storage buckets create $BUCKET \\"
    echo "  [DRY-RUN]       --location=$REGION \\"
    echo "  [DRY-RUN]       --uniform-bucket-level-access \\"
    echo "  [DRY-RUN]       --project=$PROJECT"
else
    gcloud storage buckets describe "$BUCKET" \
        --project="$PROJECT" &>/dev/null \
    || gcloud storage buckets create "$BUCKET" \
        --location="$REGION" \
        --uniform-bucket-level-access \
        --project="$PROJECT"
fi

echo ""

# ---------------------------------------------------------------------------
# Step 4: Persistent disk for tenant state
# ---------------------------------------------------------------------------
DISK_NAME="hermes-fleet-state-disk"
DISK_SIZE="50GB"
DISK_TYPE="pd-balanced"
_info "Step 4: Persistent disk '$DISK_NAME' ($DISK_SIZE, $DISK_TYPE) in $ZONE ..."
if [[ "$DRY_RUN" == true ]]; then
    echo "  [DRY-RUN] gcloud compute disks describe $DISK_NAME --zone=$ZONE --project=$PROJECT"
    echo "  [DRY-RUN]   || gcloud compute disks create $DISK_NAME \\"
    echo "  [DRY-RUN]       --size=$DISK_SIZE \\"
    echo "  [DRY-RUN]       --type=$DISK_TYPE \\"
    echo "  [DRY-RUN]       --zone=$ZONE \\"
    echo "  [DRY-RUN]       --project=$PROJECT"
else
    gcloud compute disks describe "$DISK_NAME" \
        --zone="$ZONE" \
        --project="$PROJECT" &>/dev/null \
    || gcloud compute disks create "$DISK_NAME" \
        --size="$DISK_SIZE" \
        --type="$DISK_TYPE" \
        --zone="$ZONE" \
        --project="$PROJECT"
fi

echo ""

# ---------------------------------------------------------------------------
# Step 5: Host VM (e2-standard-8, Docker via startup script)
# ---------------------------------------------------------------------------
HOST_VM="hermes-fleet-host"
HOST_MACHINE="e2-standard-8"
HOST_DISK_SIZE="32GB"
_info "Step 5: Host VM '$HOST_VM' ($HOST_MACHINE, $HOST_DISK_SIZE boot disk) ..."

# Startup script installs Docker and enables it on boot.
# Written inline so the script is self-contained (no external file dependency).
STARTUP_SCRIPT=$(cat <<'STARTUP'
#!/bin/bash
set -euo pipefail
if ! command -v docker &>/dev/null; then
    apt-get update -y
    apt-get install -y docker.io
    systemctl enable docker
    systemctl start docker
fi
STARTUP
)

if [[ "$DRY_RUN" == true ]]; then
    echo "  [DRY-RUN] gcloud compute instances describe $HOST_VM --zone=$ZONE --project=$PROJECT"
    echo "  [DRY-RUN]   || gcloud compute instances create $HOST_VM \\"
    echo "  [DRY-RUN]       --machine-type=$HOST_MACHINE \\"
    echo "  [DRY-RUN]       --boot-disk-size=$HOST_DISK_SIZE \\"
    echo "  [DRY-RUN]       --zone=$ZONE \\"
    echo "  [DRY-RUN]       --metadata=startup-script=<docker-install-script> \\"
    echo "  [DRY-RUN]       --scopes=cloud-platform \\"
    echo "  [DRY-RUN]       --project=$PROJECT"
else
    gcloud compute instances describe "$HOST_VM" \
        --zone="$ZONE" \
        --project="$PROJECT" &>/dev/null \
    || gcloud compute instances create "$HOST_VM" \
        --machine-type="$HOST_MACHINE" \
        --boot-disk-size="$HOST_DISK_SIZE" \
        --zone="$ZONE" \
        --metadata="startup-script=${STARTUP_SCRIPT}" \
        --scopes=cloud-platform \
        --project="$PROJECT"
fi

echo ""

# ---------------------------------------------------------------------------
# Step 6: Controller VM (e2-small)
# ---------------------------------------------------------------------------
CTRL_VM="hermes-fleet-controller"
CTRL_MACHINE="e2-small"
_info "Step 6: Controller VM '$CTRL_VM' ($CTRL_MACHINE) ..."
if [[ "$DRY_RUN" == true ]]; then
    echo "  [DRY-RUN] gcloud compute instances describe $CTRL_VM --zone=$ZONE --project=$PROJECT"
    echo "  [DRY-RUN]   || gcloud compute instances create $CTRL_VM \\"
    echo "  [DRY-RUN]       --machine-type=$CTRL_MACHINE \\"
    echo "  [DRY-RUN]       --zone=$ZONE \\"
    echo "  [DRY-RUN]       --scopes=cloud-platform \\"
    echo "  [DRY-RUN]       --project=$PROJECT"
else
    gcloud compute instances describe "$CTRL_VM" \
        --zone="$ZONE" \
        --project="$PROJECT" &>/dev/null \
    || gcloud compute instances create "$CTRL_VM" \
        --machine-type="$CTRL_MACHINE" \
        --zone="$ZONE" \
        --scopes=cloud-platform \
        --project="$PROJECT"
fi

echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "  Provisioning summary"
echo "  Project   : $PROJECT"
echo "  Region    : $REGION"
echo "  Zone      : $ZONE"
echo "  AR repo   : $REGION-docker.pkg.dev/$PROJECT/hermes"
echo "  GCS bucket: $BUCKET"
echo "  Disk      : $DISK_NAME ($DISK_SIZE $DISK_TYPE) in $ZONE"
echo "  Host VM   : $HOST_VM ($HOST_MACHINE) in $ZONE"
echo "  Ctrl VM   : $CTRL_VM ($CTRL_MACHINE) in $ZONE"
if [[ "$DRY_RUN" == true ]]; then
    echo ""
    echo "  DRY-RUN complete. Re-run with --apply to create resources."
fi
echo "======================================================================"
