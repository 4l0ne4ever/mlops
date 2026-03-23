#!/bin/bash
# =============================================================================
# AgentOps — Terminate + Clean AWS Resources
#
# Separate cleanup script for runs started by run-ephemeral-ui-test.sh.
# Default behavior: full cleanup via teardown.sh (terminate EC2 + delete infra).
#
# Usage:
#   bash scripts/aws/terminate-and-clean.sh
#   bash scripts/aws/terminate-and-clean.sh --state-file scripts/aws/.last-ephemeral-run.env
#   bash scripts/aws/terminate-and-clean.sh --keep-data
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

STATE_FILE="$PROJECT_ROOT/scripts/aws/.last-ephemeral-run.env"
KEEP_DATA=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --state-file)
            STATE_FILE="${2:?missing value for --state-file}"
            shift 2
            ;;
        --keep-data)
            KEEP_DATA=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# Keep AWS account selection from .env (no hardcoded account/profile).
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    if [[ -n "${AWS_PROFILE:-}" ]]; then
        export AWS_PROFILE
    fi
fi

if [[ -f "$STATE_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$STATE_FILE"
    echo "Loaded state: $STATE_FILE"
    echo "  RUN_TAG=${RUN_TAG:-N/A}"
    echo "  INSTANCE_ID=${INSTANCE_ID:-N/A}"
    echo "  EC2_IP=${EC2_IP:-N/A}"
    echo "  ALLOC_ID=${ALLOC_ID:-N/A}"
else
    echo "State file not found: $STATE_FILE"
    echo "Proceeding with generic teardown using existing scripts."
fi

if command -v aws >/dev/null 2>&1; then
    IDENTITY_JSON="$(aws sts get-caller-identity --output json 2>/dev/null || true)"
    if [[ -n "$IDENTITY_JSON" ]]; then
        CURRENT_ARN="$(printf '%s' "$IDENTITY_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("Arn",""))')"
        CURRENT_USER="${CURRENT_ARN##*/}"
        EXPECTED_USER="${AWS_EXPECTED_USER:-}"
        EXPECTED_ARN="${AWS_EXPECTED_ARN:-}"
        if [[ -n "$EXPECTED_ARN" && "$CURRENT_ARN" != "$EXPECTED_ARN" ]]; then
            echo "AWS identity mismatch: expected ARN '$EXPECTED_ARN' but got '$CURRENT_ARN'"
            exit 1
        fi
        if [[ -n "$EXPECTED_USER" && "$CURRENT_USER" != "$EXPECTED_USER" ]]; then
            echo "AWS identity mismatch: expected user '$EXPECTED_USER' but got '$CURRENT_USER'"
            exit 1
        fi
        echo "Using AWS identity: $CURRENT_ARN"
    fi
fi

ARGS=()
if [[ "$KEEP_DATA" == "true" ]]; then
    ARGS+=("--keep-data")
fi
if [[ "$DRY_RUN" == "true" ]]; then
    ARGS+=("--dry-run")
fi

echo ""
echo "Running cleanup: scripts/aws/teardown.sh ${ARGS[@]-}"
if [[ ${#ARGS[@]} -gt 0 ]]; then
    bash "$PROJECT_ROOT/scripts/aws/teardown.sh" "${ARGS[@]}"
else
    bash "$PROJECT_ROOT/scripts/aws/teardown.sh"
fi

if [[ "$DRY_RUN" == "false" && -f "$STATE_FILE" ]]; then
    rm -f "$STATE_FILE"
    echo "Removed state file: $STATE_FILE"
fi

