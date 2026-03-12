#!/bin/bash
# Full AWS resource audit — checks EVERYTHING
set -euo pipefail

export AWS_PAGER=""
export AWS_ACCESS_KEY_ID=$(grep '^AWS_ACCESS_KEY_ID=' "$(dirname "$0")/../../.env" | cut -d'=' -f2)
export AWS_SECRET_ACCESS_KEY=$(grep '^AWS_SECRET_ACCESS_KEY=' "$(dirname "$0")/../../.env" | cut -d'=' -f2)
export AWS_DEFAULT_REGION=$(grep '^AWS_DEFAULT_REGION=' "$(dirname "$0")/../../.env" | cut -d'=' -f2)

REGION="$AWS_DEFAULT_REGION"

echo "=============================================="
echo "AWS Resource Audit (Region: $REGION)"
echo "User: $(aws sts get-caller-identity --query 'Arn' --output text)"
echo "=============================================="

echo ""
echo "=== 1. EC2 Instances ==="
aws ec2 describe-instances \
  --query "Reservations[*].Instances[*].[InstanceId,State.Name,InstanceType,Tags[?Key=='Name'].Value|[0]]" \
  --output table 2>&1 || echo "  None"

echo ""
echo "=== 2. Elastic IPs ==="
EIP_COUNT=$(aws ec2 describe-addresses --query "length(Addresses)" --output text)
if [ "$EIP_COUNT" = "0" ]; then
  echo "  None"
else
  aws ec2 describe-addresses --query "Addresses[*].[PublicIp,AllocationId,InstanceId]" --output table
fi

echo ""
echo "=== 3. Security Groups (non-default) ==="
aws ec2 describe-security-groups \
  --query "SecurityGroups[?GroupName!='default'].[GroupId,GroupName,Description]" \
  --output table 2>&1 || echo "  None"

echo ""
echo "=== 4. EBS Volumes ==="
VOL_COUNT=$(aws ec2 describe-volumes --query "length(Volumes)" --output text)
if [ "$VOL_COUNT" = "0" ]; then
  echo "  None"
else
  aws ec2 describe-volumes --query "Volumes[*].[VolumeId,State,Size,VolumeType]" --output table
fi

echo ""
echo "=== 5. Key Pairs ==="
KP_COUNT=$(aws ec2 describe-key-pairs --query "length(KeyPairs)" --output text)
if [ "$KP_COUNT" = "0" ]; then
  echo "  None"
else
  aws ec2 describe-key-pairs --query "KeyPairs[*].[KeyName,KeyPairId]" --output table
fi

echo ""
echo "=== 6. DynamoDB Tables ==="
aws dynamodb list-tables --query "TableNames" --output text 2>&1 || echo "  None"

echo ""
echo "=== 7. Lambda Functions ==="
LAMBDA_COUNT=$(aws lambda list-functions --query "length(Functions)" --output text)
if [ "$LAMBDA_COUNT" = "0" ]; then
  echo "  None"
else
  aws lambda list-functions --query "Functions[*].[FunctionName,Runtime]" --output table
fi

echo ""
echo "=== 8. S3 Buckets ==="
aws s3 ls 2>&1 || echo "  None"

echo ""
echo "=== 9. NAT Gateways ==="
NAT_COUNT=$(aws ec2 describe-nat-gateways --filter "Name=state,Values=available,pending" --query "length(NatGateways)" --output text)
if [ "$NAT_COUNT" = "0" ]; then
  echo "  None"
else
  aws ec2 describe-nat-gateways --filter "Name=state,Values=available,pending" --query "NatGateways[*].[NatGatewayId,State]" --output table
fi

echo ""
echo "=== 10. IAM Roles (agentops-*) ==="
aws iam list-roles --query "Roles[?contains(RoleName,'agentops')].[RoleName]" --output text 2>&1 || echo "  None"

echo ""
echo "=== 11. CloudWatch Log Groups (agentops-*) ==="
aws logs describe-log-groups --log-group-name-prefix "/aws/lambda/agentops" --query "logGroups[*].[logGroupName,storedBytes]" --output table 2>&1 || echo "  None"

echo ""
echo "=== 12. Snapshots ==="
SNAP_COUNT=$(aws ec2 describe-snapshots --owner-ids self --query "length(Snapshots)" --output text)
if [ "$SNAP_COUNT" = "0" ]; then
  echo "  None"
else
  aws ec2 describe-snapshots --owner-ids self --query "Snapshots[*].[SnapshotId,VolumeSize,State]" --output table
fi

echo ""
echo "=============================================="
echo "Audit complete"
echo "=============================================="
