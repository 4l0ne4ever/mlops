#!/bin/bash
# =============================================================================
# AgentOps — Launch EC2 Instance
# Creates t3.small Ubuntu 22.04, allocates Elastic IP, associates it.
# =============================================================================

set -euo pipefail

# --- Load credentials from .env ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

if [ -f "$ENV_FILE" ]; then
    export AWS_ACCESS_KEY_ID=$(grep '^AWS_ACCESS_KEY_ID=' "$ENV_FILE" | cut -d'=' -f2)
    export AWS_SECRET_ACCESS_KEY=$(grep '^AWS_SECRET_ACCESS_KEY=' "$ENV_FILE" | cut -d'=' -f2)
    export AWS_DEFAULT_REGION=$(grep '^AWS_DEFAULT_REGION=' "$ENV_FILE" | cut -d'=' -f2)
    echo "Loaded credentials from .env (Key: ...${AWS_ACCESS_KEY_ID: -5})"
else
    echo "ERROR: .env not found at $ENV_FILE"
    exit 1
fi

export AWS_PAGER=""
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
SG_ID="sg-060e853ed35d2df17"

# Check if already running
echo ""
echo "Checking for existing agentops instances..."
EXISTING=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=agentops-platform" \
              "Name=instance-state-name,Values=running,pending" \
    --query "Reservations[*].Instances[0].InstanceId" \
    --output text --region "$REGION" 2>/dev/null || echo "None")

if [ "$EXISTING" != "None" ] && [ -n "$EXISTING" ]; then
    EXISTING_IP=$(aws ec2 describe-instances \
        --instance-ids "$EXISTING" \
        --query "Reservations[0].Instances[0].PublicIpAddress" \
        --output text --region "$REGION" 2>/dev/null || echo "N/A")
    echo "Instance already running: $EXISTING ($EXISTING_IP)"
    echo "EC2_IP=$EXISTING_IP"
    exit 0
fi

# Find latest Ubuntu 22.04 AMI
echo ""
echo "[1/4] Finding Ubuntu 22.04 AMI..."
AMI_ID=$(aws ec2 describe-images \
    --owners 099720109477 \
    --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
              "Name=state,Values=available" \
    --query "Images | sort_by(@, &CreationDate) | [-1].ImageId" \
    --output text --region "$REGION")
echo "  AMI: $AMI_ID"

# Launch instance
echo ""
echo "[2/4] Launching t3.small..."
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$AMI_ID" \
    --instance-type t3.small \
    --key-name agentops-key \
    --security-group-ids "$SG_ID" \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20,"VolumeType":"gp3"}}]' \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=agentops-platform}]' \
    --query "Instances[0].InstanceId" \
    --output text --region "$REGION")
echo "  Instance: $INSTANCE_ID"

echo "  Waiting for running state..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"
echo "  Running!"

# Allocate Elastic IP
echo ""
echo "[3/4] Allocating Elastic IP..."
ALLOC_ID=$(aws ec2 allocate-address --domain vpc \
    --tag-specifications 'ResourceType=elastic-ip,Tags=[{Key=Name,Value=agentops-eip}]' \
    --query "AllocationId" --output text --region "$REGION")
echo "  Allocation: $ALLOC_ID"

# Associate
echo ""
echo "[4/4] Associating Elastic IP..."
aws ec2 associate-address \
    --instance-id "$INSTANCE_ID" \
    --allocation-id "$ALLOC_ID" \
    --region "$REGION" >/dev/null

EC2_IP=$(aws ec2 describe-addresses \
    --allocation-ids "$ALLOC_ID" \
    --query "Addresses[0].PublicIp" --output text --region "$REGION")

echo ""
echo "=============================================="
echo "EC2 instance launched!"
echo "  Instance ID: $INSTANCE_ID"
echo "  Elastic IP:  $EC2_IP"
echo "  SSH:         ssh -i ~/.ssh/agentops-key.pem ubuntu@$EC2_IP"
echo ""
echo "Wait ~60s for SSH to be ready, then:"
echo "  bash scripts/aws/deploy-to-ec2.sh $EC2_IP"
echo "=============================================="
