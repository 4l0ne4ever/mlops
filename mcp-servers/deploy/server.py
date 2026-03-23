"""
MCP Server: Deploy — manages deployment and rollback of versions.

Exposes 3 MCP tools via the **streamable-http** `/mcp` endpoint:
  - deploy_version: deploy a version to staging or production
  - rollback_version: rollback production to a previous version
  - get_deployment_status: check current deployment state

Staging vs Production model:
  - Staging (port 9001): receives new config for evaluation
  - Production (port 9000): serves live traffic with active config
  - Flow: deploy to staging → eval → if pass → promote to production

Run:
    python mcp-servers/deploy/server.py

Streamable HTTP endpoint:
    POST http://localhost:8002/mcp
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Ensure project root (with agentops package) is importable when running this
# file directly (e.g. `python mcp-servers/deploy/server.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agentops.settings import PROJECT_ROOT, DEPLOY_DATA_DIR, MCP_DEPLOY_PORT, CONFIGS_DIR

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

_PROJECT_ROOT = PROJECT_ROOT
_env_path = _PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

_local_config_path = os.environ.get(
    "APP_CONFIG", str(CONFIGS_DIR / "local.json")
)
try:
    _local_config_file = Path(_local_config_path)
    if not _local_config_file.is_absolute():
        _local_config_file = _PROJECT_ROOT / _local_config_file
    _local_config = json.loads(_local_config_file.read_text(encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError) as _exc:
    logging.getLogger(__name__).warning("Config load failed (%s), using defaults", _exc)
    _local_config = {}

_data_dir = str(DEPLOY_DATA_DIR)

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    stream=sys.stdout,
)
logger = logging.getLogger("agentops.mcp-deploy")

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

from mcp_servers.deploy.deploy_backend import LocalDeployBackend

_backend = LocalDeployBackend(data_dir=_data_dir, local_config=_local_config)

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

_port = MCP_DEPLOY_PORT
mcp = FastMCP("agentops-deploy", port=_port)


@mcp.tool()
def deploy_version(version_id: str, environment: str) -> str:
    """
    Deploy a specific version to target environment.

    Pulls config from storage, updates the target app, and verifies health.
    Staging deploys are for evaluation; production deploys serve live traffic.

    Args:
        version_id: The UUID of the version to deploy.
        environment: Target environment — "staging" or "production".

    Returns:
        JSON string with deployment_id, status, and endpoint_url.
    """
    result = _backend.deploy_version(version_id, environment)
    return json.dumps(result, indent=2)


@mcp.tool()
def rollback_version(target_version_id: str) -> str:
    """
    Rollback production to a specific previous version.

    Restores config from the target version and restarts the production app.

    Args:
        target_version_id: The UUID of the version to rollback to.

    Returns:
        JSON string with deployment_id and status.
    """
    result = _backend.rollback_version(target_version_id)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_deployment_status(
    deployment_id: str = "",
    environment: str = "",
) -> str:
    """
    Get current deployment status.

    Query by deployment_id to get a specific deployment record,
    or by environment to get the current state of staging/production.

    Args:
        deployment_id: Specific deployment to look up (optional).
        environment: "staging" or "production" — get current state (optional).

    Returns:
        JSON string with current_version_id, status, uptime info.
    """
    result = _backend.get_deployment_status(
        deployment_id=deployment_id,
        environment=environment,
    )
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting MCP Deploy Server on port %d (streamable-http transport)", _port)
    mcp.run(transport="streamable-http")
