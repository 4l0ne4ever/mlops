#!/bin/bash
# =============================================================================
# AgentOps — AWS Infrastructure Provisioning
# Creates S3 bucket, DynamoDB tables, and Elastic IP.
# Requires AWS CLI configured with proper credentials.
# Usage: bash scripts/aws/provision-infra.sh
# =============================================================================

set -euo pipefail

# --- Load credentials from .env (single source of truth) ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

if [ -f "$ENV_FILE" ]; then
    set -a
    # Source .env, skipping comments and blank lines
    grep -v '^#' "$ENV_FILE" | grep -v '^$' | while IFS='=' read -r key value; do
        export "$key=$value"
    done
    # Use a simpler approach: export vars directly
    export AWS_ACCESS_KEY_ID=$(grep '^AWS_ACCESS_KEY_ID=' "$ENV_FILE" | cut -d'=' -f2)
    export AWS_SECRET_ACCESS_KEY=$(grep '^AWS_SECRET_ACCESS_KEY=' "$ENV_FILE" | cut -d'=' -f2)
    export AWS_DEFAULT_REGION=$(grep '^AWS_DEFAULT_REGION=' "$ENV_FILE" | cut -d'=' -f2)
    set +a
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

echo "=============================================="
echo "AgentOps — Provision AWS Infrastructure"
echo "Region: $REGION"
echo "=============================================="

# --- S3 Bucket ---
echo ""
echo "[1/4] Creating S3 bucket: $S3_BUCKET"
if aws s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
    echo "  Bucket already exists"
else
    if [ "$REGION" = "us-east-1" ]; then
        # us-east-1 does NOT accept LocationConstraint
        aws s3api create-bucket \
            --bucket "$S3_BUCKET" \
            --region "$REGION"
    else
        aws s3api create-bucket \
            --bucket "$S3_BUCKET" \
            --region "$REGION" \
            --create-bucket-configuration LocationConstraint="$REGION"
    fi

    # Enable versioning
    aws s3api put-bucket-versioning \
        --bucket "$S3_BUCKET" \
        --versioning-configuration Status=Enabled

    echo "  Created with versioning enabled"
fi

# --- DynamoDB: agentops-versions ---
echo ""
echo "[2/4] Creating DynamoDB table: $VERSIONS_TABLE"
if aws dynamodb describe-table --table-name "$VERSIONS_TABLE" --region "$REGION" >/dev/null 2>&1; then
    echo "  Table already exists"
else
    aws dynamodb create-table \
        --table-name "$VERSIONS_TABLE" \
        --attribute-definitions \
            AttributeName=version_id,AttributeType=S \
            AttributeName=prompt_hash,AttributeType=S \
            AttributeName=created_at,AttributeType=S \
        --key-schema \
            AttributeName=version_id,KeyType=HASH \
        --global-secondary-indexes \
            '[{
                "IndexName": "prompt_hash-index",
                "KeySchema": [
                    {"AttributeName": "prompt_hash", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"}
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}
            }]' \
        --provisioned-throughput \
            ReadCapacityUnits=5,WriteCapacityUnits=5 \
        --region "$REGION"

    echo "  Created with GSI: prompt_hash-index"
    echo "  Waiting for table to become active..."
    aws dynamodb wait table-exists --table-name "$VERSIONS_TABLE" --region "$REGION"
    echo "  Table active"
fi

# --- DynamoDB: agentops-eval-runs ---
echo ""
echo "[3/4] Creating DynamoDB table: $EVAL_RUNS_TABLE"
if aws dynamodb describe-table --table-name "$EVAL_RUNS_TABLE" --region "$REGION" >/dev/null 2>&1; then
    echo "  Table already exists"
else
    aws dynamodb create-table \
        --table-name "$EVAL_RUNS_TABLE" \
        --attribute-definitions \
            AttributeName=run_id,AttributeType=S \
            AttributeName=started_at,AttributeType=S \
            AttributeName=version_id,AttributeType=S \
        --key-schema \
            AttributeName=run_id,KeyType=HASH \
            AttributeName=started_at,KeyType=RANGE \
        --global-secondary-indexes \
            '[{
                "IndexName": "version_id-index",
                "KeySchema": [
                    {"AttributeName": "version_id", "KeyType": "HASH"},
                    {"AttributeName": "started_at", "KeyType": "RANGE"}
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}
            }]' \
        --provisioned-throughput \
            ReadCapacityUnits=5,WriteCapacityUnits=5 \
        --region "$REGION"

    echo "  Created with GSI: version_id-index"
    echo "  Waiting for table to become active..."
    aws dynamodb wait table-exists --table-name "$EVAL_RUNS_TABLE" --region "$REGION"
    echo "  Table active"
fi

# --- Lambda: GitHub Webhook Handler ---
echo ""
echo "[4/6] Creating Lambda function: agentops-webhook"

LAMBDA_ROLE_NAME="agentops-lambda-role"
LAMBDA_FUNCTION_NAME="agentops-webhook"
# SCRIPT_DIR already set at top of script

# Create Lambda execution role if not exists
if aws iam get-role --role-name "$LAMBDA_ROLE_NAME" >/dev/null 2>&1; then
    echo "  IAM role already exists"
    LAMBDA_ROLE_ARN=$(aws iam get-role --role-name "$LAMBDA_ROLE_NAME" --query 'Role.Arn' --output text)
else
    LAMBDA_ROLE_ARN=$(aws iam create-role \
        --role-name "$LAMBDA_ROLE_NAME" \
        --assume-role-policy-document file://"$SCRIPT_DIR/lambda-trust-policy.json" \
        --query 'Role.Arn' --output text)

    # Attach basic execution policy (CloudWatch Logs)
    aws iam attach-role-policy \
        --role-name "$LAMBDA_ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

    echo "  Created IAM role: $LAMBDA_ROLE_ARN"
    echo "  Waiting 10s for IAM propagation..."
    sleep 10
fi

# Package and create/update Lambda function
if aws lambda get-function --function-name "$LAMBDA_FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
    echo "  Lambda function already exists — updating code..."
    cd "$SCRIPT_DIR" && zip -j /tmp/agentops-lambda.zip lambda_handler.py
    aws lambda update-function-code \
        --function-name "$LAMBDA_FUNCTION_NAME" \
        --zip-file fileb:///tmp/agentops-lambda.zip \
        --region "$REGION" >/dev/null
    echo "  Code updated"
else
    cd "$SCRIPT_DIR" && zip -j /tmp/agentops-lambda.zip lambda_handler.py
    aws lambda create-function \
        --function-name "$LAMBDA_FUNCTION_NAME" \
        --runtime python3.11 \
        --handler lambda_handler.lambda_handler \
        --zip-file fileb:///tmp/agentops-lambda.zip \
        --role "$LAMBDA_ROLE_ARN" \
        --timeout 30 \
        --memory-size 128 \
        --region "$REGION" >/dev/null
    echo "  Created Lambda function"
fi

# Create/ensure Lambda Function URL exists
LAMBDA_URL=$(aws lambda get-function-url-config \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --region "$REGION" \
    --query 'FunctionUrl' --output text 2>/dev/null || echo "")

if [ -z "$LAMBDA_URL" ] || [ "$LAMBDA_URL" = "None" ]; then
    # Add resource-based policy for public access
    aws lambda add-permission \
        --function-name "$LAMBDA_FUNCTION_NAME" \
        --statement-id FunctionURLAllowPublicAccess \
        --action lambda:InvokeFunctionUrl \
        --principal "*" \
        --function-url-auth-type NONE \
        --region "$REGION" 2>/dev/null || true

    LAMBDA_URL=$(aws lambda create-function-url-config \
        --function-name "$LAMBDA_FUNCTION_NAME" \
        --auth-type NONE \
        --region "$REGION" \
        --query 'FunctionUrl' --output text)
    echo "  Created Function URL: $LAMBDA_URL"
else
    echo "  Function URL exists: $LAMBDA_URL"
fi

# --- EC2: Security Group ---
echo ""
echo "[5/6] Security Group: agentops-sg"

SG_NAME="agentops-sg"
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" \
    --query "Vpcs[0].VpcId" --output text --region "$REGION")

SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
    --query "SecurityGroups[0].GroupId" --output text --region "$REGION" 2>/dev/null || echo "None")

if [ "$SG_ID" = "None" ] || [ -z "$SG_ID" ]; then
    SG_ID=$(aws ec2 create-security-group \
        --group-name "$SG_NAME" \
        --description "AgentOps platform - SSH + HTTP" \
        --vpc-id "$VPC_ID" \
        --region "$REGION" \
        --query 'GroupId' --output text)

    # SSH
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
        --protocol tcp --port 22 --cidr 0.0.0.0/0 --region "$REGION" >/dev/null
    # HTTP (nginx)
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
        --protocol tcp --port 80 --cidr 0.0.0.0/0 --region "$REGION" >/dev/null
    # Orchestrator
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
        --protocol tcp --port 7000 --cidr 0.0.0.0/0 --region "$REGION" >/dev/null
    # Target App prod/staging
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
        --protocol tcp --port 9000 --cidr 0.0.0.0/0 --region "$REGION" >/dev/null
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
        --protocol tcp --port 9001 --cidr 0.0.0.0/0 --region "$REGION" >/dev/null
    echo "  Created: $SG_ID (SSH + HTTP + ports 7000, 9000, 9001)"
else
    echo "  Already exists: $SG_ID"
fi

# --- Elastic IP ---
echo ""
echo "[6/6] Elastic IP"
echo "  NOTE: Allocate after launching EC2 instance:"
echo "    ALLOC_ID=\$(aws ec2 allocate-address --domain vpc --region $REGION --query 'AllocationId' --output text)"
echo "    aws ec2 associate-address --instance-id <INSTANCE_ID> --allocation-id \$ALLOC_ID --region $REGION"

echo ""
echo "=============================================="
echo "✅ AWS infrastructure provisioned!"
echo ""
echo "Resources created:"
echo "  S3:       s3://$S3_BUCKET (versioning ON)"
echo "  DynamoDB: $VERSIONS_TABLE (PK: version_id)"
echo "  DynamoDB: $EVAL_RUNS_TABLE (PK: run_id, SK: started_at)"
echo "  Lambda:   $LAMBDA_FUNCTION_NAME"
echo "  URL:      $LAMBDA_URL"
echo "  SG:       $SG_ID"
echo ""
echo "Next steps:"
echo "  1. Launch EC2 t3.small with SG=$SG_ID"
echo "  2. Allocate & attach Elastic IP"
echo "  3. SSH in, run: sudo bash scripts/setup-ec2.sh"
echo "  4. Run: bash scripts/aws/deploy-to-ec2.sh <EC2_IP>"
echo "  5. Configure GitHub webhook → $LAMBDA_URL"
echo "  6. Set Lambda env var: EC2_ENDPOINT=http://<ELASTIC_IP>:7000"
echo "=============================================="
