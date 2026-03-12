#!/bin/bash
# =============================================================================
# AgentOps — Local Development Setup
# Creates venvs and installs dependencies for all Python services.
# Run from project root: bash scripts/setup-local.sh
# =============================================================================

set -euo pipefail

PYTHON=${PYTHON:-python3.11}
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=============================================="
echo "AgentOps — Local Setup"
echo "Python: $($PYTHON --version 2>&1)"
echo "Root:   $PROJECT_ROOT"
echo "=============================================="

# --- Helper function ---
setup_venv() {
    local service_dir="$1"
    local service_name="$2"

    local full_path="$PROJECT_ROOT/$service_dir"

    if [ ! -d "$full_path" ]; then
        echo "  SKIP: $full_path does not exist yet"
        return
    fi

    echo ""
    echo "[$service_name] Setting up venv..."

    if [ ! -d "$full_path/venv" ]; then
        $PYTHON -m venv "$full_path/venv"
        echo "  Created venv"
    else
        echo "  Venv already exists"
    fi

    if [ -f "$full_path/requirements.txt" ]; then
        "$full_path/venv/bin/pip" install --upgrade pip -q
        "$full_path/venv/bin/pip" install -r "$full_path/requirements.txt" -q
        echo "  Installed dependencies"
    else
        echo "  No requirements.txt found — skipping pip install"
    fi
}

# --- Setup each service ---
setup_venv "target-app" "Target App (Translation Agent)"
setup_venv "mcp-servers/storage" "MCP Server: Storage"
setup_venv "mcp-servers/monitor" "MCP Server: Monitor"
setup_venv "mcp-servers/deploy" "MCP Server: Deploy"
setup_venv "agents/orchestrator" "Orchestrator Agent"
setup_venv "poc" "POC Spike"

# --- Copy .env if needed ---
if [ ! -f "$PROJECT_ROOT/.env" ] && [ -f "$PROJECT_ROOT/.env.example" ]; then
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    echo ""
    echo "Created .env from .env.example — fill in the values!"
fi

echo ""
echo "=============================================="
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Fill in .env with your API keys"
echo "  2. cd target-app && source venv/bin/activate"
echo "  3. uvicorn app:app --port 9000 --reload"
echo "=============================================="
