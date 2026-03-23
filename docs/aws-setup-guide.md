# AWS Setup & Deployment Guide

> **Mục đích:** Hướng dẫn step-by-step để provision AWS, deploy code lên EC2, verify, rồi teardown.  
> **Cost estimate:** < $1 nếu chạy vài giờ rồi terminate.  
> **Prerequisite:** AWS CLI configured (`aws configure`)

---

## Quick Summary

```bash
# 1. Provision AWS resources (S3, DynamoDB, Lambda, SG)
bash scripts/aws/provision-infra.sh

# 2. Launch EC2 manually (console) → get IP

# 3. Setup EC2 OS
ssh -i ~/.ssh/agentops-key.pem ubuntu@<EC2_IP>
sudo bash /tmp/setup-ec2.sh

# 4. Deploy code + start services
bash scripts/aws/deploy-to-ec2.sh <EC2_IP> ~/.ssh/agentops-key.pem

# 5. Verify everything
bash scripts/aws/verify-ec2.sh <EC2_IP> ~/.ssh/agentops-key.pem

# 6. Seed baseline
ssh -i ~/.ssh/agentops-key.pem ubuntu@<EC2_IP> \
    'cd /opt/agentops && source .venv/bin/activate && python scripts/seed-baseline.py'

# 7. Teardown khi xong
bash scripts/aws/teardown.sh
```

---

## Detailed Steps

### Step 1: AWS CLI Check

```bash
aws sts get-caller-identity
# Should show your account ID and IAM user
```

If not configured:

```bash
aws configure
# Access Key: from .env (AWS_ACCESS_KEY_ID)
# Secret Key: from .env (AWS_SECRET_ACCESS_KEY)
# Region: us-east-1
# Output: json
```

### Step 2: Provision Infrastructure

```bash
bash scripts/aws/provision-infra.sh
```

Creates:

- S3 bucket: `agentops-storage` (versioning ON)
- DynamoDB: `agentops-versions` (PK: version_id)
- DynamoDB: `agentops-eval-runs` (PK: run_id, SK: started_at)
- Lambda: `agentops-webhook` with Function URL
- Security Group: `agentops-sg` (SSH + HTTP + ports)

**Save the Lambda Function URL** — you'll need it for GitHub webhook.

### Step 3: Launch EC2 Instance

Via AWS Console (easier for one-time setup):

1. Go to [EC2 Console](https://console.aws.amazon.com/ec2)
2. **Launch Instance:**
   - Name: `agentops-platform`
   - AMI: **Ubuntu 22.04 LTS** (x86_64)
   - Type: **t3.small** (2 vCPU, 2 GB RAM)
   - Key pair: Create or select existing (download .pem file)
   - Security group: Select `agentops-sg`
   - Storage: 20 GB gp3 (default 8GB may be tight)
3. **Launch**
4. Wait for "Running" status

Or via CLI:

```bash
# Find latest Ubuntu 22.04 AMI
AMI_ID=$(aws ec2 describe-images \
    --owners 099720109477 \
    --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
    --query "Images | sort_by(@, &CreationDate) | [-1].ImageId" \
    --output text --region us-east-1)

# Get Security Group ID
SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=agentops-sg" \
    --query "SecurityGroups[0].GroupId" --output text --region us-east-1)

# Launch instance
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$AMI_ID" \
    --instance-type t3.small \
    --key-name agentops-key \
    --security-group-ids "$SG_ID" \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20,"VolumeType":"gp3"}}]' \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=agentops-platform}]' \
    --region us-east-1 \
    --query 'Instances[0].InstanceId' --output text)

echo "Instance: $INSTANCE_ID"

# Wait for running
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region us-east-1
```

### Step 4: Allocate & Attach Elastic IP

```bash
ALLOC_ID=$(aws ec2 allocate-address --domain vpc --region us-east-1 \
    --query 'AllocationId' --output text)

aws ec2 associate-address \
    --instance-id "$INSTANCE_ID" \
    --allocation-id "$ALLOC_ID" \
    --region us-east-1

EC2_IP=$(aws ec2 describe-addresses \
    --allocation-ids "$ALLOC_ID" \
    --query 'Addresses[0].PublicIp' --output text --region us-east-1)

echo "Elastic IP: $EC2_IP"
```

**⚠️ Nhớ update `.env`:**

```bash
echo "EC2_ELASTIC_IP=$EC2_IP" >> .env
```

### Step 5: Setup EC2 OS

```bash
# Copy setup script
scp -i ~/.ssh/agentops-key.pem scripts/setup-ec2.sh ubuntu@$EC2_IP:/tmp/

# SSH in and run
ssh -i ~/.ssh/agentops-key.pem ubuntu@$EC2_IP
sudo bash /tmp/setup-ec2.sh
exit
```

### Step 6: Deploy Code to EC2

```bash
bash scripts/aws/deploy-to-ec2.sh $EC2_IP ~/.ssh/agentops-key.pem
```

This:

- Syncs all project files via rsync
- Uploads .env
- Creates per-service venvs with pinned dependencies
- Installs systemd service files
- Configures nginx
- Starts all 5 services

### Step 7: Verify Deployment

```bash
bash scripts/aws/verify-ec2.sh $EC2_IP ~/.ssh/agentops-key.pem
```

Manual checks:

```bash
# Health check
curl http://$EC2_IP:9000/health
curl http://$EC2_IP:9001/health

# Test translation
curl -X POST http://$EC2_IP:9000/translate \
    -H "Content-Type: application/json" \
    -d '{"text": "Xin chào", "source_lang": "vi", "target_lang": "en"}'
```

### Step 8: Seed Baseline (AWS version)

```bash
ssh -i ~/.ssh/agentops-key.pem ubuntu@$EC2_IP << 'EOF'
cd /opt/agentops
source .venv/bin/activate
python scripts/seed-baseline.py
EOF
```

### Step 9: Configure GitHub Webhook

1. Go to GitHub repo → **Settings** → **Webhooks** → **Add webhook**
2. **Payload URL:** `<Lambda Function URL from Step 2>`
3. **Content type:** `application/json`
4. **Secret:** Same as `GITHUB_WEBHOOK_SECRET` in `.env`
5. **Events:** Just the push event
6. Click **Add webhook**

Then set Lambda environment variable:

```bash
aws lambda update-function-configuration \
    --function-name agentops-webhook \
    --environment "Variables={EC2_ENDPOINT=http://$EC2_IP:7000,GITHUB_WEBHOOK_SECRET=$(grep GITHUB_WEBHOOK_SECRET .env | cut -d= -f2)}" \
    --region us-east-1
```

### Step 10: Test Webhook (Optional)

Push a small commit to the repo and check:

```bash
# Check Lambda logs
aws logs tail /aws/lambda/agentops-webhook --since 5m --region us-east-1
```

---

## Teardown (After Testing)

**⚠️ This deletes EVERYTHING:**

```bash
# Dry run first (see what will be deleted)
bash scripts/aws/teardown.sh --dry-run

# Actually delete
bash scripts/aws/teardown.sh
```

Options:

- `--dry-run`: Show what would be deleted without doing it
- `--keep-data`: Keep S3 + DynamoDB, delete compute (EC2, Lambda, SG, EIP)

---

## Cost Breakdown

| Resource                   | Hourly Cost | Monthly (if kept) |
| -------------------------- | ----------- | ----------------- |
| EC2 t3.small               | $0.0208/hr  | ~$15              |
| Elastic IP (attached)      | $0.005/hr   | ~$3.60            |
| Elastic IP (unattached)    | $0.005/hr   | ~$3.60            |
| S3 (< 5GB)                 | Free tier   | Free              |
| DynamoDB (< 25 RCU/WCU)    | Free tier   | Free              |
| Lambda (< 1M requests)     | Free tier   | Free              |
| **Total (few hours test)** |             | **< $1**          |

**⚠️ Elastic IP charges** even when not attached! Always release when done.

---

## Troubleshooting

### Service won't start

```bash
ssh ubuntu@$EC2_IP
sudo journalctl -u agentops-target-prod -n 50
sudo journalctl -u agentops-mcp-storage -n 50
```

### OOM (Out of Memory)

```bash
free -h
# If < 100MB available, consider t3.medium (~$30/month)
```

### Port not accessible

```bash
# Check security group
aws ec2 describe-security-groups --group-names agentops-sg --region us-east-1
# Check service is listening
ssh ubuntu@$EC2_IP "ss -tlnp | grep -E '(8000|8001|8002|9000|9001)'"
```

### Lambda not triggering

```bash
# Check Function URL exists
aws lambda get-function-url-config --function-name agentops-webhook --region us-east-1
# Check logs
aws logs tail /aws/lambda/agentops-webhook --since 1h --region us-east-1
```
