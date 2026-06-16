#!/usr/bin/env bash
# deploy-controller.sh — deploy the fleet controller onto the co-located VM.
#
# OPERATOR-RUN ONLY (live step). Runs from your workstation; uses `gcloud compute
# scp/ssh` to push the controller onto the VM created by provision-host.sh.
#
# The controller is STDLIB-ONLY (see fleet/controller/requirements.txt) — no venv,
# no pip on the VM. It runs as the `hermes-fleet` user (uid 10001, created by
# vm-startup.sh) under systemd, reading /etc/hermes-fleet/controller.env.
#
# Prereqs:
#   - provision-host.sh --apply already ran (VM + SA + AR + bucket exist).
#   - The fleet image is built+pushed (cloudbuild.fleet.yaml).
#   - You filled an env file from fleet/controller/.env.example with REAL values
#     (CONVEX_URL admin url, WORKER_SECRET, IMAGE=<pushed ref>, MINIMAX/Sendblue/etc).
#
# Usage:
#   ./deploy-controller.sh --env-file /path/to/controller.env \
#       [--project P] [--zone Z] [--vm NAME] [--smoke] [--apply | --dry-run]
#
#   --smoke   run one reconcile pass (`controller.py --once`) on the VM and exit,
#             BEFORE installing the systemd service (catches a bad env early).
#
# Exit codes: 0 success/dry-run; 1 precondition/fatal.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTROLLER_SRC="$(cd "${SCRIPT_DIR}/../../fleet/controller" && pwd)"

PROJECT="${PROJECT:-hermes-saved-content-lab}"
ZONE="${ZONE:-us-central1-a}"
VM="${VM:-hermes-fleet-host}"
ENV_FILE=""
SMOKE=false
DRY_RUN=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)  PROJECT="$2"; shift 2 ;;
        --zone)     ZONE="$2";    shift 2 ;;
        --vm)       VM="$2";      shift 2 ;;
        --env-file) ENV_FILE="$2"; shift 2 ;;
        --smoke)    SMOKE=true;   shift ;;
        --apply)    DRY_RUN=false; shift ;;
        --dry-run)  DRY_RUN=true;  shift ;;
        *) echo "ERROR: unknown argument: $1" >&2; exit 1 ;;
    esac
done

_info()  { echo "[INFO]  $*"; }
_error() { echo "[ERROR] $*" >&2; }
_abort() { _error "$*"; exit 1; }

ssh_vm() {  # ssh_vm "<remote shell command>"
    local cmd="$1"
    if [[ "$DRY_RUN" == true ]]; then echo "  [DRY-RUN] gcloud compute ssh $VM --zone=$ZONE --project=$PROJECT --command=\"$cmd\""; return 0; fi
    gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --command="$cmd"
}
scp_vm() {  # scp_vm <local> <remote>
    if [[ "$DRY_RUN" == true ]]; then echo "  [DRY-RUN] gcloud compute scp --recurse $1 $VM:$2 --zone=$ZONE --project=$PROJECT"; return 0; fi
    gcloud compute scp --recurse "$1" "$VM:$2" --zone="$ZONE" --project="$PROJECT"
}

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------
command -v gcloud &>/dev/null || _abort "gcloud not found"
[[ -n "$ENV_FILE" ]] || _abort "--env-file is required (fill from fleet/controller/.env.example)"
[[ -f "$ENV_FILE" ]] || _abort "env file not found: $ENV_FILE"
[[ -d "$CONTROLLER_SRC" ]] || _abort "controller source not found: $CONTROLLER_SRC"

# Validate required keys are present + non-empty (fail fast, before any live step).
REQUIRED=(CONVEX_URL WORKER_SECRET IMAGE MINIMAX_API_KEY SENDBLUE_API_KEY_ID SENDBLUE_API_SECRET_KEY SENDBLUE_FROM_NUMBER)
for k in "${REQUIRED[@]}"; do
    grep -qE "^${k}=.+" "$ENV_FILE" || _abort "env file missing required key: ${k}"
done
# Common mistake guard: the controller POSTs to the ADMIN api on .convex.cloud.
grep -qE "^CONVEX_URL=.*\.convex\.cloud" "$ENV_FILE" \
    || _error "WARN: CONVEX_URL should be the .convex.cloud ADMIN url (not .convex.site)"

echo "======================================================================"
echo "  Deploy fleet controller -> $VM ($ZONE, $PROJECT)"
echo "  controller src: $CONTROLLER_SRC"
echo "  env file:       $ENV_FILE ($(grep -cE '^[A-Z].*=' "$ENV_FILE") keys)"
echo "  MODE=$([[ "$DRY_RUN" == true ]] && echo DRY-RUN || echo APPLY)$([[ "$SMOKE" == true ]] && echo ' +smoke')"
echo "======================================================================"

# ---------------------------------------------------------------------------
# 1. Stage controller code + env on the VM (to /tmp first; root not required for scp)
# ---------------------------------------------------------------------------
_info "1. copy controller code + env to VM /tmp"
# Only the runtime .py files (skip tests/caches) — copy the dir, prune on the VM.
scp_vm "$CONTROLLER_SRC" "/tmp/hermes-controller-src"
scp_vm "$ENV_FILE" "/tmp/controller.env.staged"

# ---------------------------------------------------------------------------
# 2. Install into /opt/hermes-fleet/controller + /etc/hermes-fleet (root, via sudo)
# ---------------------------------------------------------------------------
_info "2. install code, env (0600), and systemd unit"
ssh_vm "set -e; \
    sudo rm -rf /opt/hermes-fleet/controller && \
    sudo mkdir -p /opt/hermes-fleet/controller && \
    sudo cp /tmp/hermes-controller-src/*.py /opt/hermes-fleet/controller/ && \
    sudo cp /tmp/hermes-controller-src/hermes-controller.service /etc/systemd/system/hermes-controller.service && \
    sudo install -o hermes-fleet -g hermes-fleet -m 0600 /tmp/controller.env.staged /etc/hermes-fleet/controller.env && \
    sudo chown -R hermes-fleet:hermes-fleet /opt/hermes-fleet/controller && \
    rm -f /tmp/controller.env.staged && rm -rf /tmp/hermes-controller-src"

# ---------------------------------------------------------------------------
# 3. Optional smoke: one reconcile pass as hermes-fleet, reading the real env.
# ---------------------------------------------------------------------------
if [[ "$SMOKE" == true ]]; then
    _info "3. smoke: one reconcile pass (--once) as hermes-fleet"
    ssh_vm "sudo -u hermes-fleet bash -lc 'set -a; . /etc/hermes-fleet/controller.env; set +a; \
        cd /opt/hermes-fleet/controller && /usr/bin/python3 controller.py --once'"
fi

# ---------------------------------------------------------------------------
# 4. Start under systemd
# ---------------------------------------------------------------------------
_info "4. enable + (re)start hermes-controller via systemd"
# `enable --now` is a NO-OP on an already-running unit, so a redeploy would keep
# the OLD code. `restart` always reloads the freshly-copied .py files.
ssh_vm "sudo systemctl daemon-reload && sudo systemctl enable hermes-controller && \
    sudo systemctl restart hermes-controller && \
    sleep 2 && sudo systemctl --no-pager --full status hermes-controller | head -20"

echo ""
echo "Done. Tail logs with:"
echo "  gcloud compute ssh $VM --zone=$ZONE --project=$PROJECT --command='sudo journalctl -u hermes-controller -f'"
