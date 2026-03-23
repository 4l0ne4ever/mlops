#!/bin/bash
# =============================================================================
# AgentOps — AWS UI/System Test Runner (NO AUTO CLEANUP)
#
# Creates infra + EC2, deploys services, and verifies runtime behavior.
# Does NOT terminate/clean automatically. Use terminate-and-clean.sh afterwards.
#
# Usage:
#   bash scripts/aws/run-ephemeral-ui-test.sh [--key-path ~/.ssh/agentops-key.pem]
#                                            [--instance-type t3.small]
#                                            [--state-file scripts/aws/.last-ephemeral-run.env]
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

KEY_PATH="$HOME/.ssh/agentops-key.pem"
INSTANCE_TYPE="t3.small"
STATE_FILE="$PROJECT_ROOT/scripts/aws/.last-ephemeral-run.env"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --key-path)
            KEY_PATH="${2:?missing value for --key-path}"
            shift 2
            ;;
        --instance-type)
            INSTANCE_TYPE="${2:?missing value for --instance-type}"
            shift 2
            ;;
        --state-file)
            STATE_FILE="${2:?missing value for --state-file}"
            shift
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

if [[ ! -f "$KEY_PATH" ]]; then
    echo "SSH key not found: $KEY_PATH"
    exit 1
fi

# Avoid local proxy settings breaking AWS CLI/curl in this automation.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

ENV_FILE="$PROJECT_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    echo ".env not found at $ENV_FILE"
    exit 1
fi

# Load env first (single source of truth; no hardcoded account/profile).
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# Optional AWS profile from .env (preferred when multiple IAM users/accounts exist).
if [[ -n "${AWS_PROFILE:-}" ]]; then
    export AWS_PROFILE
fi

AWS_REGION="${AWS_DEFAULT_REGION:-}"
if [[ -z "${AWS_REGION:-}" ]]; then
    AWS_REGION="us-east-1"
fi
export AWS_DEFAULT_REGION="$AWS_REGION"
export AWS_PAGER=""

# Fail fast if current identity is not the expected one from .env.
IDENTITY_JSON="$(aws sts get-caller-identity --output json)"
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

KEY_NAME="$(basename "$KEY_PATH" .pem)"
RUN_TAG="agentops-ephemeral-$(date +%Y%m%d-%H%M%S)"
INSTANCE_ID=""
EC2_IP=""
ALLOC_ID=""
SMOKE_RETRIES="${SMOKE_RETRIES:-8}"
SMOKE_SLEEP_SEC="${SMOKE_SLEEP_SEC:-3}"

wait_for_http_200() {
    local url="$1"
    local label="$2"
    local code=""
    local attempt=1
    while [[ "$attempt" -le "$SMOKE_RETRIES" ]]; do
        code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" || true)"
        if [[ "$code" == "200" ]]; then
            echo "$label healthy (attempt $attempt/$SMOKE_RETRIES)"
            return 0
        fi
        echo "$label not ready yet (attempt $attempt/$SMOKE_RETRIES, code=$code)"
        sleep "$SMOKE_SLEEP_SEC"
        attempt=$((attempt + 1))
    done
    echo "$label failed after $SMOKE_RETRIES attempts (last code=$code)"
    return 1
}

wait_for_http_200_remote() {
    local url="$1"
    local label="$2"
    local code=""
    local attempt=1
    while [[ "$attempt" -le "$SMOKE_RETRIES" ]]; do
        code="$(ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no "ubuntu@$EC2_IP" "curl -s -o /dev/null -w '%{http_code}' --max-time 5 '$url' 2>/dev/null || echo 000" || true)"
        if [[ "$code" == "200" ]]; then
            echo "$label healthy (attempt $attempt/$SMOKE_RETRIES)"
            return 0
        fi
        echo "$label not ready yet (attempt $attempt/$SMOKE_RETRIES, code=$code)"
        sleep "$SMOKE_SLEEP_SEC"
        attempt=$((attempt + 1))
    done
    echo "$label failed after $SMOKE_RETRIES attempts (last code=$code)"
    return 1
}

echo "=============================================="
echo "AgentOps Ephemeral AWS UI/System Test"
echo "Mode:   init + run only (manual cleanup later)"
echo "Region: $AWS_REGION"
echo "AWS ARN: $CURRENT_ARN"
echo "Key:    $KEY_PATH (key name: $KEY_NAME)"
echo "Tag:    $RUN_TAG"
echo "State:  $STATE_FILE"
echo "=============================================="

echo ""
echo "[1/9] Provisioning base infra (S3/DynamoDB/Lambda/SG)..."
bash "$PROJECT_ROOT/scripts/aws/provision-infra.sh"

echo ""
echo "[2/9] Ensuring EC2 key pair exists..."
if aws ec2 describe-key-pairs \
    --region "$AWS_REGION" \
    --key-names "$KEY_NAME" >/dev/null 2>&1; then
    echo "  Key pair exists: $KEY_NAME"
else
    echo "  Key pair not found in AWS. Importing from $KEY_PATH ..."
    PUB_KEY_TMP="$(mktemp)"
    ssh-keygen -y -f "$KEY_PATH" > "$PUB_KEY_TMP"
    aws ec2 import-key-pair \
        --region "$AWS_REGION" \
        --key-name "$KEY_NAME" \
        --public-key-material "fileb://$PUB_KEY_TMP" >/dev/null
    rm -f "$PUB_KEY_TMP"
    echo "  Imported key pair: $KEY_NAME"
fi

echo ""
echo "[3/9] Discovering SG + Ubuntu AMI..."
SG_ID="$(aws ec2 describe-security-groups \
    --region "$AWS_REGION" \
    --filters "Name=group-name,Values=agentops-sg" \
    --query "SecurityGroups[0].GroupId" \
    --output text)"

if [[ -z "${SG_ID:-}" || "$SG_ID" == "None" ]]; then
    echo "Could not resolve security group agentops-sg"
    exit 1
fi

AMI_ID="$(aws ec2 describe-images \
    --region "$AWS_REGION" \
    --owners 099720109477 \
    --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
    --query "Images | sort_by(@, &CreationDate) | [-1].ImageId" \
    --output text)"

if [[ -z "${AMI_ID:-}" || "$AMI_ID" == "None" ]]; then
    echo "Could not resolve Ubuntu AMI"
    exit 1
fi

echo ""
echo "[4/9] Launching EC2 instance..."
INSTANCE_ID="$(aws ec2 run-instances \
    --region "$AWS_REGION" \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SG_ID" \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20,"VolumeType":"gp3"}}]' \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$RUN_TAG}]" \
    --query "Instances[0].InstanceId" \
    --output text)"

echo "  Instance ID: $INSTANCE_ID"
aws ec2 wait instance-running --region "$AWS_REGION" --instance-ids "$INSTANCE_ID"

echo ""
echo "[5/9] Allocating + attaching Elastic IP..."
ALLOC_ID="$(aws ec2 allocate-address \
    --region "$AWS_REGION" \
    --domain vpc \
    --query "AllocationId" \
    --output text)"

aws ec2 associate-address \
    --region "$AWS_REGION" \
    --instance-id "$INSTANCE_ID" \
    --allocation-id "$ALLOC_ID" >/dev/null

EC2_IP="$(aws ec2 describe-addresses \
    --region "$AWS_REGION" \
    --allocation-ids "$ALLOC_ID" \
    --query "Addresses[0].PublicIp" \
    --output text)"
echo "  Public IP: $EC2_IP"

mkdir -p "$(dirname "$STATE_FILE")"
cat > "$STATE_FILE" <<EOF
RUN_TAG=$RUN_TAG
AWS_REGION=$AWS_REGION
INSTANCE_ID=$INSTANCE_ID
EC2_IP=$EC2_IP
ALLOC_ID=$ALLOC_ID
KEY_PATH=$KEY_PATH
INSTANCE_TYPE=$INSTANCE_TYPE
CREATED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF
echo "  State saved to: $STATE_FILE"

echo ""
echo "[6/9] Bootstrapping EC2 OS..."
scp -i "$KEY_PATH" -o StrictHostKeyChecking=no \
    "$PROJECT_ROOT/scripts/setup-ec2.sh" "ubuntu@$EC2_IP:/tmp/setup-ec2.sh"
ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no \
    "ubuntu@$EC2_IP" "sudo bash /tmp/setup-ec2.sh"

echo ""
echo "[7/9] Deploying AgentOps services to EC2..."
bash "$PROJECT_ROOT/scripts/aws/deploy-to-ec2.sh" "$EC2_IP" "$KEY_PATH"

echo ""
echo "[8/9] Running server/system verification..."
bash "$PROJECT_ROOT/scripts/aws/verify-ec2.sh" "$EC2_IP" "$KEY_PATH"

echo ""
echo "[9/9] Running runtime smoke requests..."
wait_for_http_200_remote "http://127.0.0.1:9000/health" "Production health"
wait_for_http_200_remote "http://127.0.0.1:9001/health" "Staging health"

TRANSLATE_RESP="$(curl -s -X POST "http://$EC2_IP:9000/translate" \
    -H "Content-Type: application/json" \
    -d '{"text":"Xin chao","source_lang":"vi","target_lang":"en"}')"
echo "Translate smoke response: ${TRANSLATE_RESP:0:220}"

echo ""
echo "AWS test run completed successfully."
echo ""
echo "Resources are STILL RUNNING (no auto-cleanup)."
echo "When ready, terminate with:"
echo "  bash scripts/aws/terminate-and-clean.sh --state-file \"$STATE_FILE\""

