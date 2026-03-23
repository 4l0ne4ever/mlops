#!/bin/bash
# =============================================================================
# AgentOps — Verify EC2 Deployment
#
# Run from LOCAL machine after deploy-to-ec2.sh.
# Tests all services are running and healthy on EC2.
#
# Usage:
#   bash scripts/aws/verify-ec2.sh <EC2_IP> [SSH_KEY_PATH]
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
SSH_CMD="ssh -i $SSH_KEY -o StrictHostKeyChecking=no $EC2_USER@$EC2_IP"

# Shared ports (keep in sync with agentops.settings defaults)
TARGET_APP_PROD_PORT="${TARGET_APP_PROD_PORT:-9000}"
TARGET_APP_STAGING_PORT="${TARGET_APP_STAGING_PORT:-9001}"
MCP_STORAGE_PORT="${MCP_STORAGE_PORT:-8000}"
MCP_MONITOR_PORT="${MCP_MONITOR_PORT:-8001}"
MCP_DEPLOY_PORT="${MCP_DEPLOY_PORT:-8002}"

PASS=0
FAIL=0
SERVICE_ACTIVE_RETRIES="${SERVICE_ACTIVE_RETRIES:-8}"
SERVICE_ACTIVE_SLEEP_SEC="${SERVICE_ACTIVE_SLEEP_SEC:-3}"

check() {
    local name="$1"
    local result="$2"
    if [ "$result" = "0" ]; then
        PASS=$((PASS + 1))
        echo "  ✅ $name"
    else
        FAIL=$((FAIL + 1))
        echo "  ❌ $name"
    fi
}

echo "=============================================="
echo "AgentOps — EC2 Verification"
echo "  Host: $EC2_IP"
echo "=============================================="

# --- 1. Service status ---
echo ""
echo "[1/5] Systemd services"

SERVICES=(agentops-target-prod agentops-target-staging agentops-mcp-storage agentops-mcp-monitor agentops-mcp-deploy agentops-orchestrator agentops-dashboard)
for svc in "${SERVICES[@]}"; do
    STATUS=""
    for ((i=1; i<=SERVICE_ACTIVE_RETRIES; i++)); do
        STATUS=$($SSH_CMD "systemctl is-active $svc 2>/dev/null" || echo "inactive")
        if [ "$STATUS" = "active" ]; then
            break
        fi
        sleep "$SERVICE_ACTIVE_SLEEP_SEC"
    done
    check "$svc = $STATUS" "$([ "$STATUS" = "active" ] && echo 0 || echo 1)"
done

# --- 2. Health endpoints ---
echo ""
echo "[2/5] Health endpoints"

# Target app production (check from inside EC2 to avoid local network port filtering)
HTTP_CODE=$($SSH_CMD "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:$TARGET_APP_PROD_PORT/health 2>/dev/null || echo 000")
check "Target App Production ($TARGET_APP_PROD_PORT): $HTTP_CODE" "$([ "$HTTP_CODE" = "200" ] && echo 0 || echo 1)"

# Target app staging (check from inside EC2 to avoid local network port filtering)
HTTP_CODE=$($SSH_CMD "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:$TARGET_APP_STAGING_PORT/health 2>/dev/null || echo 000")
check "Target App Staging ($TARGET_APP_STAGING_PORT): $HTTP_CODE" "$([ "$HTTP_CODE" = "200" ] && echo 0 || echo 1)"

# MCP servers /mcp endpoints (streamable-http)
for port in "$MCP_STORAGE_PORT" "$MCP_MONITOR_PORT" "$MCP_DEPLOY_PORT"; do
    HTTP_CODE=$($SSH_CMD "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:$port/mcp 2>/dev/null || echo 000")
    # For /mcp, 200 = OK, 405/406 also indicate the endpoint exists but method/header may be off.
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "405" ] || [ "$HTTP_CODE" = "406" ]; then
        check "MCP Server ($port) /mcp reachable: $HTTP_CODE" "0"
    else
        check "MCP Server ($port) /mcp reachable: $HTTP_CODE" "1"
    fi
done

# Dashboard via nginx root
HTTP_CODE=$($SSH_CMD "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1/ 2>/dev/null || echo 000")
check "Dashboard via nginx (/): $HTTP_CODE" "$([ "$HTTP_CODE" = "200" ] && echo 0 || echo 1)"

# --- 3. Memory usage ---
echo ""
echo "[3/5] Memory usage"
$SSH_CMD "free -h | head -2"
MEM_AVAIL=$($SSH_CMD "free -m | awk '/^Mem:/{print \$7}'" 2>/dev/null || echo "0")
check "Available memory > 200MB ($MEM_AVAIL MB)" "$([ "$MEM_AVAIL" -gt 200 ] && echo 0 || echo 1)"

# --- 4. Disk usage ---
echo ""
echo "[4/5] Disk usage"
$SSH_CMD "df -h / | tail -1"
DISK_AVAIL=$($SSH_CMD "df / | tail -1 | awk '{print \$4}'" 2>/dev/null || echo "0")
check "Disk available > 1GB" "$([ "$DISK_AVAIL" -gt 1000000 ] && echo 0 || echo 1)"

# --- 5. Run Phase 0 & Phase 1 tests on EC2 ---
echo ""
echo "[5/5] Running tests on EC2..."

$SSH_CMD << 'REMOTE_TESTS'
cd /opt/agentops

# Need a unified venv for running tests (they import from multiple services)
if [ ! -d .venv ]; then
    python3.11 -m venv .venv
    .venv/bin/pip install --upgrade pip -q 2>/dev/null
    .venv/bin/pip install -r requirements.txt -q 2>/dev/null
fi

source .venv/bin/activate

echo ""
echo "--- Phase 0 Tests ---"
python tests/test_phase0.py 2>&1 | tail -5

echo ""
echo "--- Phase 1 Tests ---"
python tests/test_phase1.py 2>&1 | tail -5
REMOTE_TESTS

echo ""
echo "=============================================="
TOTAL=$((PASS + FAIL))
echo "Verification: $PASS passed, $FAIL failed, $TOTAL total"
if [ "$FAIL" -eq 0 ]; then
    echo "🎉 ALL CHECKS PASSED"
else
    echo "⚠️  $FAIL check(s) FAILED — review above"
fi
echo "=============================================="
