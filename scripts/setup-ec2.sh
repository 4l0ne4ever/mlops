#!/bin/bash
# =============================================================================
# AgentOps — EC2 Instance Setup (Ubuntu 22.04)
# Run on a fresh EC2 t3.small instance after SSH.
# Usage: sudo bash scripts/setup-ec2.sh
# =============================================================================

set -euo pipefail

echo "=============================================="
echo "AgentOps — EC2 Setup (Ubuntu 22.04)"
echo "=============================================="

# --- System packages ---
echo ""
echo "[1/6] Updating system packages..."
apt-get update -y
apt-get upgrade -y

# --- Python 3.11 ---
echo ""
echo "[2/6] Installing Python 3.11..."
apt-get install -y software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update -y
apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip
echo "  System python3: $(python3 --version)"
echo "  Python 3.11:    $(python3.11 --version)"

# --- Node.js LTS (configurable) ---
echo ""
NODE_MAJOR="${NODE_MAJOR:-20}"
echo "[3/6] Installing Node.js ${NODE_MAJOR}.x..."
curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
apt-get install -y nodejs
echo "  Node version: $(node --version)"
echo "  npm version:  $(npm --version)"

# --- Docker (recommended) ---
echo ""
echo "[4/6] Installing Docker..."
apt-get install -y docker.io
systemctl enable docker
systemctl start docker
usermod -aG docker ubuntu
echo "  Docker version: $(docker --version)"

# --- nginx ---
echo ""
echo "[5/6] Installing nginx..."
apt-get install -y nginx
systemctl enable nginx

# --- Project directory ---
echo ""
echo "[6/6] Setting up project directory..."
mkdir -p /opt/agentops
chown -R ubuntu:ubuntu /opt/agentops

# Create log directory
mkdir -p /var/log/agentops
chown -R ubuntu:ubuntu /var/log/agentops

echo ""
echo "=============================================="
echo "✅ EC2 setup complete!"
echo ""
echo "Next steps (as ubuntu user):"
echo "  1. cd /opt/agentops"
echo "  2. git clone <repo-url> ."
echo "  3. bash scripts/setup-local.sh"
echo "  4. Fill in .env"
echo "  5. sudo cp scripts/nginx/agentops.conf /etc/nginx/sites-available/agentops"
echo "  6. sudo ln -sf /etc/nginx/sites-available/agentops /etc/nginx/sites-enabled/"
echo "  7. sudo nginx -t && sudo systemctl reload nginx"
echo "=============================================="
