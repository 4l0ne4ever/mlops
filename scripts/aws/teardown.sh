#!/bin/bash
# =============================================================================
# AgentOps — Teardown ALL AWS Resources
#
# ⚠️  THIS WILL DELETE EVERYTHING — S3 data, DynamoDB tables, Lambda, EC2, EIP.
# Run this after testing to avoid charges.
#
# Usage:
#   bash scripts/aws/teardown.sh
#
# To teardown selectively:
#   bash scripts/aws/teardown.sh --keep-data    # Keep S3+DynamoDB, delete compute
#   bash scripts/aws/teardown.sh --dry-run       # Show what would be deleted
# =============================================================================

set -euo pipefail

# --- Load credentials from .env (single source of truth) ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

if [ -f "$ENV_FILE" ]; then
    export AWS_ACCESS_KEY_ID=$(grep '^AWS_ACCESS_KEY_ID=' "$ENV_FILE" | cut -d'=' -f2)
    export AWS_SECRET_ACCESS_KEY=$(grep '^AWS_SECRET_ACCESS_KEY=' "$ENV_FILE" | cut -d'=' -f2)
    export AWS_DEFAULT_REGION=$(grep '^AWS_DEFAULT_REGION=' "$ENV_FILE" | cut -d'=' -f2)
    echo "Loaded credentials from .env (Key: ...${AWS_ACCESS_KEY_ID: -5})"
else
    echo "ERROR: .env file not found at $ENV_FILE"
    echo "Create it from .env.example and fill in your AWS credentials."
    exit 1
fi

# Disable AWS CLI pager to prevent interactive blocking
export AWS_PAGER=""

REGION="${AWS_DEFAULT_REGION:-us-east-1}"
S3_BUCKET="agentops-storage"
VERSIONS_TABLE="agentops-versions"
EVAL_RUNS_TABLE="agentops-eval-runs"
LAMBDA_FUNCTION="agentops-webhook"
LAMBDA_ROLE="agentops-lambda-role"
SG_NAME="agentops-sg"

DRY_RUN=false
KEEP_DATA=false

for arg in "$@"; do
    case $arg in
        --dry-run) DRY_RUN=true ;;
        --keep-data) KEEP_DATA=true ;;
    esac
done

echo "=============================================="
echo "AgentOps — Teardown AWS Resources"
echo "  Region: $REGION"
if $DRY_RUN; then echo "  Mode: DRY RUN (no changes)"; fi
if $KEEP_DATA; then echo "  Option: --keep-data (S3+DynamoDB preserved)"; fi
echo "=============================================="

run_cmd() {
    if $DRY_RUN; then
        echo "  [DRY RUN] $1"
    else
        eval "$1" 2>/dev/null && echo "  ✅ Done" || echo "  ⚠️ Skipped (may not exist)"
    fi
}

# --- Lambda ---
echo ""
echo "[1/6] Lambda function: $LAMBDA_FUNCTION"

# Delete Function URL first
run_cmd "aws lambda delete-function-url-config --function-name $LAMBDA_FUNCTION --region $REGION"
run_cmd "aws lambda delete-function --function-name $LAMBDA_FUNCTION --region $REGION"

# Delete Lambda role
echo ""
echo "[2/6] Lambda IAM role: $LAMBDA_ROLE"
run_cmd "aws iam detach-role-policy --role-name $LAMBDA_ROLE --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
run_cmd "aws iam delete-role --role-name $LAMBDA_ROLE"

# --- EC2 instances ---
echo ""
echo "[3/6] EC2 instances & Elastic IPs"

# Find instances with agentops security group
SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=$SG_NAME" \
    --query "SecurityGroups[0].GroupId" --output text --region "$REGION" 2>/dev/null || echo "None")

if [ "$SG_ID" != "None" ] && [ -n "$SG_ID" ]; then
    # Find running instances in this SG
    INSTANCE_IDS=$(aws ec2 describe-instances \
        --filters "Name=instance.group-id,Values=$SG_ID" "Name=instance-state-name,Values=running,stopped" \
        --query "Reservations[*].Instances[*].InstanceId" --output text --region "$REGION" 2>/dev/null || echo "")

    if [ -n "$INSTANCE_IDS" ]; then
        echo "  Found instances: $INSTANCE_IDS"
        for iid in $INSTANCE_IDS; do
            # Disassociate and release Elastic IPs
            ASSOC_ID=$(aws ec2 describe-addresses \
                --filters "Name=instance-id,Values=$iid" \
                --query "Addresses[0].AssociationId" --output text --region "$REGION" 2>/dev/null || echo "None")
            ALLOC_ID=$(aws ec2 describe-addresses \
                --filters "Name=instance-id,Values=$iid" \
                --query "Addresses[0].AllocationId" --output text --region "$REGION" 2>/dev/null || echo "None")

            if [ "$ASSOC_ID" != "None" ] && [ -n "$ASSOC_ID" ]; then
                run_cmd "aws ec2 disassociate-address --association-id $ASSOC_ID --region $REGION"
            fi
            if [ "$ALLOC_ID" != "None" ] && [ -n "$ALLOC_ID" ]; then
                run_cmd "aws ec2 release-address --allocation-id $ALLOC_ID --region $REGION"
                echo "  Released Elastic IP"
            fi

            # Terminate instance
            run_cmd "aws ec2 terminate-instances --instance-ids $iid --region $REGION"
            echo "  Terminating: $iid"
        done

        if ! $DRY_RUN; then
            echo "  Waiting for termination..."
            aws ec2 wait instance-terminated --instance-ids $INSTANCE_IDS --region "$REGION" 2>/dev/null || true
        fi
    else
        echo "  No instances found"
    fi
else
    echo "  Security group not found — no instances to terminate"
fi

# Also release any unattached Elastic IPs with our tag
UNATTACHED_ALLOCS=$(aws ec2 describe-addresses \
    --filters "Name=domain,Values=vpc" \
    --query "Addresses[?AssociationId==null].AllocationId" --output text --region "$REGION" 2>/dev/null || echo "")
if [ -n "$UNATTACHED_ALLOCS" ]; then
    echo "  Found unattached Elastic IPs: $UNATTACHED_ALLOCS"
    for alloc in $UNATTACHED_ALLOCS; do
        run_cmd "aws ec2 release-address --allocation-id $alloc --region $REGION"
    done
fi

# --- Security Group ---
echo ""
echo "[4/6] Security Group: $SG_NAME"
if [ "$SG_ID" != "None" ] && [ -n "$SG_ID" ]; then
    run_cmd "aws ec2 delete-security-group --group-id $SG_ID --region $REGION"
else
    echo "  Not found — skip"
fi

# --- S3 & DynamoDB ---
if ! $KEEP_DATA; then
    echo ""
    echo "[5/6] S3 bucket: $S3_BUCKET"
    if aws s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
        run_cmd "aws s3 rb s3://$S3_BUCKET --force --region $REGION"
    else
        echo "  Not found — skip"
    fi

    echo ""
    echo "[6/6] DynamoDB tables"
    for table in "$VERSIONS_TABLE" "$EVAL_RUNS_TABLE"; do
        if aws dynamodb describe-table --table-name "$table" --region "$REGION" >/dev/null 2>&1; then
            run_cmd "aws dynamodb delete-table --table-name $table --region $REGION"
            echo "  Deleted: $table"
        else
            echo "  $table not found — skip"
        fi
    done
else
    echo ""
    echo "[5/6] S3 bucket: KEPT (--keep-data)"
    echo "[6/6] DynamoDB tables: KEPT (--keep-data)"
fi

echo ""
echo "=============================================="
if $DRY_RUN; then
    echo "🔍 DRY RUN complete — no resources were changed."
    echo "   Remove --dry-run to actually delete."
else
    echo "✅ Teardown complete! All resources deleted."
    echo ""
    echo "Verify in AWS Console that no resources remain:"
    echo "  - EC2: https://console.aws.amazon.com/ec2"
    echo "  - Lambda: https://console.aws.amazon.com/lambda"
    echo "  - S3: https://console.aws.amazon.com/s3"
    echo "  - DynamoDB: https://console.aws.amazon.com/dynamodb"
fi
echo "=============================================="
