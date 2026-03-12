#!/bin/bash
# =============================================================================
# AgentOps — Deploy Code to EC2
#
# Syncs project files to EC2, sets up per-service venvs, and starts services.
# Prerequisite: EC2 instance running, setup-ec2.sh already executed.
#
# Usage:
#   bash scripts/aws/deploy-to-ec2.sh <EC2_IP> [SSH_KEY_PATH]
#
# Example:
#   bash scripts/aws/deploy-to-ec2.sh 54.1.2.3 ~/.ssh/agentops-key.pem
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

EC2_IP="${1:?Usage: $0 <EC2_IP> [SSH_KEY_PATH]}"
SSH_KEY="${2:-~/.ssh/agentops-key.pem}"
EC2_USER="ubuntu"
REMOTE_DIR="/opt/agentops"

echo "=============================================="
echo "AgentOps — Deploy to EC2"
echo "  Host: $EC2_USER@$EC2_IP"
echo "  Key:  $SSH_KEY"
echo "  Dir:  $REMOTE_DIR"
echo "=============================================="

SSH_CMD="ssh -i $SSH_KEY -o StrictHostKeyChecking=no $EC2_USER@$EC2_IP"
SCP_CMD="scp -i $SSH_KEY -o StrictHostKeyChecking=no"

# --- Step 1: Sync project files ---
echo ""
echo "[1/5] Syncing project files to EC2..."

# Use rsync to sync (excludes venvs, caches, local data)
rsync -avz --delete \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '.local-data/' \
    --exclude '.git/' \
    --exclude 'node_modules/' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    --exclude 'venv/' \
    ./ "$EC2_USER@$EC2_IP:$REMOTE_DIR/"

echo "  ✅ Files synced"

# --- Step 2: Upload .env (separately, not in git) ---
echo ""
echo "[2/5] Uploading .env..."
if [ -f .env ]; then
    # Create a temporary copy with absolute paths for EC2
    cp .env /tmp/agentops-ec2.env
    sed -i.bak "s|APP_CONFIG=configs/|APP_CONFIG=$REMOTE_DIR/configs/|" /tmp/agentops-ec2.env
    sed -i.bak "s|PROMPT_TEMPLATE_PATH=configs/|PROMPT_TEMPLATE_PATH=$REMOTE_DIR/configs/|" /tmp/agentops-ec2.env
    sed -i.bak "s|MODEL_CONFIG_PATH=configs/|MODEL_CONFIG_PATH=$REMOTE_DIR/configs/|" /tmp/agentops-ec2.env
    sed -i.bak "s|THRESHOLDS_CONFIG_PATH=configs/|THRESHOLDS_CONFIG_PATH=$REMOTE_DIR/configs/|" /tmp/agentops-ec2.env
    # Use production config on EC2
    sed -i.bak "s|APP_CONFIG=$REMOTE_DIR/configs/local.json|APP_CONFIG=$REMOTE_DIR/configs/production.json|" /tmp/agentops-ec2.env
    rm -f /tmp/agentops-ec2.env.bak
    $SCP_CMD /tmp/agentops-ec2.env "$EC2_USER@$EC2_IP:$REMOTE_DIR/.env"
    rm -f /tmp/agentops-ec2.env
    echo "  ✅ .env uploaded (paths converted to absolute, using production config)"
else
    echo "  ⚠️ No .env found — make sure to create one on EC2"
fi

# --- Step 3: Create per-service venvs and install deps ---
echo ""
echo "[3/5] Setting up per-service venvs on EC2..."

$SSH_CMD << 'SETUP_VENVS'
set -euo pipefail
REMOTE_DIR="/opt/agentops"
cd "$REMOTE_DIR"

PYTHON=python3.11

setup_svc() {
    local dir="$1"
    local name="$2"
    echo "  [$name] Setting up..."
    if [ ! -d "$dir" ]; then
        echo "    SKIP: $dir not found"
        return
    fi
    cd "$REMOTE_DIR/$dir"
    if [ ! -d venv ]; then
        $PYTHON -m venv venv
        echo "    Created venv"
    fi
    if [ -f requirements.txt ]; then
        venv/bin/pip install --upgrade pip -q 2>/dev/null
        venv/bin/pip install -r requirements.txt -q 2>/dev/null
        echo "    Installed deps"
    fi
    cd "$REMOTE_DIR"
}

setup_svc "target-app" "Target App"
setup_svc "mcp-servers/storage" "MCP Storage"
setup_svc "mcp-servers/monitor" "MCP Monitor"
setup_svc "mcp-servers/deploy" "MCP Deploy"
setup_svc "poc" "POC Spike"

echo "  ✅ All venvs ready"
SETUP_VENVS

# --- Step 4: Install systemd services ---
echo ""
echo "[4/5] Installing systemd services..."

$SSH_CMD << 'INSTALL_SERVICES'
set -euo pipefail
REMOTE_DIR="/opt/agentops"

# Create log directory
sudo mkdir -p /var/log/agentops
sudo chown -R ubuntu:ubuntu /var/log/agentops

# Create .local-data directory for services
mkdir -p "$REMOTE_DIR/.local-data"/{versions,eval-results,metrics,logs,deployments}

# Extract and install individual service files from the combined conf
# Target App Production
sudo tee /etc/systemd/system/agentops-target-prod.service > /dev/null << 'SVC'
[Unit]
Description=AgentOps Target App (Production)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/agentops/target-app
Environment=APP_CONFIG=/opt/agentops/configs/production.json
EnvironmentFile=/opt/agentops/.env
ExecStart=/opt/agentops/target-app/venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 9000
Restart=always
RestartSec=5
StandardOutput=append:/var/log/agentops/target-prod.log
StandardError=append:/var/log/agentops/target-prod.error.log

[Install]
WantedBy=multi-user.target
SVC

# Target App Staging
sudo tee /etc/systemd/system/agentops-target-staging.service > /dev/null << 'SVC'
[Unit]
Description=AgentOps Target App (Staging)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/agentops/target-app
Environment=APP_CONFIG=/opt/agentops/configs/production.json
EnvironmentFile=/opt/agentops/.env
ExecStart=/opt/agentops/target-app/venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 9001
Restart=always
RestartSec=5
StandardOutput=append:/var/log/agentops/target-staging.log
StandardError=append:/var/log/agentops/target-staging.error.log

[Install]
WantedBy=multi-user.target
SVC

# MCP Storage Server
sudo tee /etc/systemd/system/agentops-mcp-storage.service > /dev/null << 'SVC'
[Unit]
Description=AgentOps MCP Server - Storage
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/agentops/mcp-servers/storage
EnvironmentFile=/opt/agentops/.env
ExecStart=/opt/agentops/mcp-servers/storage/venv/bin/python server.py
Restart=always
RestartSec=5
StandardOutput=append:/var/log/agentops/mcp-storage.log
StandardError=append:/var/log/agentops/mcp-storage.error.log

[Install]
WantedBy=multi-user.target
SVC

# MCP Monitor Server
sudo tee /etc/systemd/system/agentops-mcp-monitor.service > /dev/null << 'SVC'
[Unit]
Description=AgentOps MCP Server - Monitor
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/agentops/mcp-servers/monitor
EnvironmentFile=/opt/agentops/.env
ExecStart=/opt/agentops/mcp-servers/monitor/venv/bin/python server.py
Restart=always
RestartSec=5
StandardOutput=append:/var/log/agentops/mcp-monitor.log
StandardError=append:/var/log/agentops/mcp-monitor.error.log

[Install]
WantedBy=multi-user.target
SVC

# MCP Deploy Server
sudo tee /etc/systemd/system/agentops-mcp-deploy.service > /dev/null << 'SVC'
[Unit]
Description=AgentOps MCP Server - Deploy
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/agentops/mcp-servers/deploy
EnvironmentFile=/opt/agentops/.env
ExecStart=/opt/agentops/mcp-servers/deploy/venv/bin/python server.py
Restart=always
RestartSec=5
StandardOutput=append:/var/log/agentops/mcp-deploy.log
StandardError=append:/var/log/agentops/mcp-deploy.error.log

[Install]
WantedBy=multi-user.target
SVC

# Install nginx config
sudo cp "$REMOTE_DIR/scripts/nginx/agentops.conf" /etc/nginx/sites-available/agentops
sudo ln -sf /etc/nginx/sites-available/agentops /etc/nginx/sites-enabled/agentops
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# Reload systemd
sudo systemctl daemon-reload

echo "  ✅ Systemd services installed"
INSTALL_SERVICES

# --- Step 5: Start all services ---
echo ""
echo "[5/5] Starting services..."

$SSH_CMD << 'START_SERVICES'
set -euo pipefail

SERVICES=(
    agentops-target-prod
    agentops-target-staging
    agentops-mcp-storage
    agentops-mcp-monitor
    agentops-mcp-deploy
)

for svc in "${SERVICES[@]}"; do
    sudo systemctl enable "$svc" 2>/dev/null
    sudo systemctl restart "$svc"
    echo "  Started: $svc"
done

# Wait for services to settle
sleep 5

echo ""
echo "  Service status:"
for svc in "${SERVICES[@]}"; do
    STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "inactive")
    if [ "$STATUS" = "active" ]; then
        echo "    ✅ $svc: $STATUS"
    else
        echo "    ❌ $svc: $STATUS"
    fi
done
START_SERVICES

echo ""
echo "=============================================="
echo "✅ Deployment complete!"
echo ""
echo "Verify:"
echo "  curl http://$EC2_IP:9000/health"
echo "  curl http://$EC2_IP:9001/health"
echo ""
echo "Seed baseline:"
echo "  $SSH_CMD 'cd $REMOTE_DIR && source .venv/bin/activate && python scripts/seed-baseline.py'"
echo "=============================================="
