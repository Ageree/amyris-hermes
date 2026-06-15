#!/usr/bin/env bash
# provision-host.sh — GCP provisioning for the Hermes fleet (M6, v1 single-VM).
#
# OPERATOR-RUN ONLY. Requires:
#   - A funded GCP project with billing enabled.
#   - gcloud CLI installed and authenticated (gcloud auth login / ADC).
#   - Run with --apply to actually create resources; omit it (or --dry-run) for a
#     safe preview of the commands that WOULD run.
#
# v1 topology = ONE co-located VM that runs BOTH the controller (systemd) and the
# per-tenant containers (docker). No separate controller VM, no unattached disk:
# tenant state lives on the boot disk under /data/tenants and is mirrored to GCS.
#
# Idempotent: each create is guarded by a describe-or-create probe; IAM bindings
# and `services enable` are idempotent by nature. Every gcloud call passes
# --project=$PROJECT explicitly so it never touches the gcloud default project.
#
# Usage:
#   ./provision-host.sh [--project P] [--region R] [--zone Z]
#                       [--machine-type M] [--apply | --dry-run]
#
# Exit codes: 0 success (or dry-run); 1 precondition/fatal error.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Defaults (flags override; env overrides nothing — flags/defaults only)
# ---------------------------------------------------------------------------
PROJECT="${PROJECT:-hermes-saved-content-lab}"
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-us-central1-a}"
AR_REPO="saved-content"          # MUST match cloudbuild.fleet.yaml _AR_REPO + .env IMAGE
BUCKET_NAME="hermes-fleet-state"
SA_NAME="hermes-fleet"
HOST_VM="hermes-fleet-host"
# e2-standard-2 = 2 vCPU / 8 GB. ponytail: capacity scales with RAM. 8 GB holds the
# controller + TWO chromium-running tenants (the isolation proof) with headroom;
# e2-medium (4 GB) only fits a single tenant. Bump higher + raise CAPACITY_PER_HOST
# to pack more tenants per host.
HOST_MACHINE="e2-standard-2"
BOOT_DISK_SIZE="50GB"            # image (multi-GB) + /data/tenants state + chromium cache
DRY_RUN=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)      PROJECT="$2"; shift 2 ;;
        --region)       REGION="$2";  shift 2 ;;
        --zone)         ZONE="$2";    shift 2 ;;
        --machine-type) HOST_MACHINE="$2"; shift 2 ;;
        --apply)        DRY_RUN=false; shift ;;
        --dry-run)      DRY_RUN=true;  shift ;;
        *) echo "ERROR: unknown argument: $1" >&2
           echo "Usage: $0 [--project P] [--region R] [--zone Z] [--machine-type M] [--apply|--dry-run]" >&2
           exit 1 ;;
    esac
done

SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
BUCKET="gs://${BUCKET_NAME}"
AR_HOST="${REGION}-docker.pkg.dev"
IMAGE="${AR_HOST}/${PROJECT}/${AR_REPO}/hermes-fleet:latest"

_info()  { echo "[INFO]  $*"; }
_warn()  { echo "[WARN]  $*" >&2; }
_error() { echo "[ERROR] $*" >&2; }
_abort() { _error "$*"; exit 1; }

# run_cmd — execute in --apply, print in --dry-run. For idempotent commands.
run_cmd() {
    if [[ "$DRY_RUN" == true ]]; then echo "  [DRY-RUN] $*"; else "$@"; fi
}

# guarded_create <label> <probe...> -- <create...>
# Runs <create> only if <probe> fails (resource absent). In dry-run, prints create.
guarded_create() {
    local label="$1"; shift
    local probe=() create=() seen=0
    for a in "$@"; do
        if [[ "$a" == "--" ]]; then seen=1; continue; fi
        if [[ $seen -eq 0 ]]; then probe+=("$a"); else create+=("$a"); fi
    done
    _info "$label"
    if [[ "$DRY_RUN" == true ]]; then echo "  [DRY-RUN] ${create[*]}"; return 0; fi
    if "${probe[@]}" &>/dev/null; then _info "  exists — skip"; else "${create[@]}"; fi
}

# ---------------------------------------------------------------------------
echo "======================================================================"
echo "  Hermes Fleet — GCP provisioner (v1 single co-located VM)"
echo "  PROJECT=$PROJECT  REGION=$REGION  ZONE=$ZONE  MACHINE=$HOST_MACHINE"
echo "  IMAGE=$IMAGE"
echo "  MODE=$([[ "$DRY_RUN" == true ]] && echo DRY-RUN || echo APPLY)"
echo "======================================================================"
echo ""

# ---------------------------------------------------------------------------
# Step 0: Preconditions
# ---------------------------------------------------------------------------
_info "Step 0: preconditions"
command -v gcloud &>/dev/null || _abort "gcloud not found. https://cloud.google.com/sdk/docs/install"
_info "gcloud: $(gcloud version 2>/dev/null | head -1)"
gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>/dev/null | grep -q '@' \
    || _abort "No active gcloud account. Run: gcloud auth login"
_info "account: $(gcloud auth list --filter='status:ACTIVE' --format='value(account)' 2>/dev/null | head -1)"
[[ -f "${SCRIPT_DIR}/vm-startup.sh" ]] || _abort "missing ${SCRIPT_DIR}/vm-startup.sh"
DEFAULT_PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
[[ "$DEFAULT_PROJECT" != "$PROJECT" ]] && \
    _warn "gcloud default project '$DEFAULT_PROJECT' != target '$PROJECT' (every call passes --project)"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Enable APIs
# ---------------------------------------------------------------------------
_info "Step 1: enable APIs"
run_cmd gcloud services enable \
    compute.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    storage.googleapis.com \
    logging.googleapis.com \
    secretmanager.googleapis.com \
    --project="$PROJECT"
echo ""

# ---------------------------------------------------------------------------
# Step 2: Artifact Registry repo (saved-content)
# ---------------------------------------------------------------------------
guarded_create "Step 2: AR repo '$AR_REPO' (docker, $REGION)" \
    gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" --project="$PROJECT" \
    -- \
    gcloud artifacts repositories create "$AR_REPO" \
        --repository-format=docker --location="$REGION" \
        --description="Hermes fleet container images" --project="$PROJECT"
echo ""

# ---------------------------------------------------------------------------
# Step 3: GCS bucket + object versioning (protects state against rsync --delete)
# ---------------------------------------------------------------------------
guarded_create "Step 3: GCS bucket $BUCKET (uniform access)" \
    gcloud storage buckets describe "$BUCKET" --project="$PROJECT" \
    -- \
    gcloud storage buckets create "$BUCKET" \
        --location="$REGION" --uniform-bucket-level-access --project="$PROJECT"
_info "Step 3b: enable object versioning on $BUCKET"
run_cmd gcloud storage buckets update "$BUCKET" --versioning --project="$PROJECT"
echo ""

# ---------------------------------------------------------------------------
# Step 4: Service account + IAM
# ---------------------------------------------------------------------------
guarded_create "Step 4: service account $SA_EMAIL" \
    gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT" \
    -- \
    gcloud iam service-accounts create "$SA_NAME" \
        --display-name="Hermes fleet controller+containers" --project="$PROJECT"

_info "Step 4b: IAM — artifactregistry.reader (docker pull) + logging.logWriter (project)"
run_cmd gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA_EMAIL" --role="roles/artifactregistry.reader" --condition=None
run_cmd gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA_EMAIL" --role="roles/logging.logWriter" --condition=None

_info "Step 4c: IAM — storage.objectAdmin scoped to the state bucket (least privilege)"
run_cmd gcloud storage buckets add-iam-policy-binding "$BUCKET" \
    --member="serviceAccount:$SA_EMAIL" --role="roles/storage.objectAdmin" --project="$PROJECT"

# ponytail: PER_INSTANCE_SECRETS defaults OFF (shared WORKER_SECRET via env). When
# you flip it on, grant secretmanager.admin here:
#   gcloud projects add-iam-policy-binding "$PROJECT" \
#       --member="serviceAccount:$SA_EMAIL" --role="roles/secretmanager.admin" --condition=None
echo ""

# ---------------------------------------------------------------------------
# Step 5: The single co-located VM (debian-12, SA attached, startup-script)
# ---------------------------------------------------------------------------
guarded_create "Step 5: VM '$HOST_VM' ($HOST_MACHINE, debian-12, $BOOT_DISK_SIZE)" \
    gcloud compute instances describe "$HOST_VM" --zone="$ZONE" --project="$PROJECT" \
    -- \
    gcloud compute instances create "$HOST_VM" \
        --machine-type="$HOST_MACHINE" \
        --image-family=debian-12 --image-project=debian-cloud \
        --boot-disk-size="$BOOT_DISK_SIZE" --boot-disk-type=pd-balanced \
        --zone="$ZONE" \
        --service-account="$SA_EMAIL" \
        --scopes=cloud-platform \
        --metadata=fleet-ar-host="$AR_HOST" \
        --metadata-from-file=startup-script="${SCRIPT_DIR}/vm-startup.sh" \
        --project="$PROJECT"
echo ""

# ---------------------------------------------------------------------------
echo "======================================================================"
echo "  Provisioning summary"
echo "  AR repo   : ${AR_HOST}/${PROJECT}/${AR_REPO}"
echo "  Image     : $IMAGE"
echo "  GCS bucket: $BUCKET (versioned)"
echo "  SA        : $SA_EMAIL (artifactregistry.reader, logging.logWriter, bucket objectAdmin)"
echo "  VM        : $HOST_VM ($HOST_MACHINE) in $ZONE — controller + containers"
if [[ "$DRY_RUN" == true ]]; then
    echo ""
    echo "  DRY-RUN complete. Re-run with --apply to create resources."
else
    echo ""
    echo "  Next: build+push the image (cloudbuild.fleet.yaml), then deploy the"
    echo "  controller onto $HOST_VM (/opt/hermes-fleet + /etc/hermes-fleet/controller.env)."
fi
echo "======================================================================"
