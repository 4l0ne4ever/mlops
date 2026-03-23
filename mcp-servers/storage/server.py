"""
MCP Server: Storage — manages prompt versions and eval results.

Exposes 5 MCP tools via the **streamable-http** `/mcp` endpoint:
  - save_prompt_version: upload prompt template, create version record
  - get_prompt_version: retrieve prompt template by version_id
  - list_versions: list all versions (newest first)
  - save_eval_result: save evaluation results
  - get_eval_results: retrieve eval results by version_id or run_id

Runtime:
    python -m mcp_servers.storage.server
    # or from project root:
    python mcp-servers/storage/server.py

Streamable HTTP endpoint:
    POST http://localhost:8000/mcp

Use the streamable-http handshake:
  1) POST `initialize`
  2) Read `mcp-session-id` header
  3) POST `notifications/initialized`
  4) POST `tools/call`
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Ensure project root (with agentops package) is importable when running this
# file directly (e.g. `python mcp-servers/storage/server.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agentops.settings import PROJECT_ROOT, STORAGE_DATA_DIR, MCP_STORAGE_PORT

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

_PROJECT_ROOT = PROJECT_ROOT
_env_path = _PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

_app_config_path = os.environ.get(
    "APP_CONFIG", str(_PROJECT_ROOT / "configs" / "local.json")
)
_app_config_file = Path(_app_config_path)
if not _app_config_file.is_absolute():
    _app_config_file = _PROJECT_ROOT / _app_config_file
_local_config: dict[str, Any] = {}
try:
    _local_config = json.loads(_app_config_file.read_text(encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError) as _exc:
    logging.getLogger(__name__).warning("Config load failed (%s), using defaults", _exc)
    _local_config = {}

# Data directory — local filesystem for dev, S3/DynamoDB on EC2
_data_dir = str(STORAGE_DATA_DIR)

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    stream=sys.stdout,
)
logger = logging.getLogger("agentops.mcp-storage")

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

from mcp_servers.storage.storage_backend import LocalStorageBackend

_backend = LocalStorageBackend(data_dir=_data_dir)

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

_port = MCP_STORAGE_PORT
mcp = FastMCP("agentops-storage", port=_port)


@mcp.tool()
def save_prompt_version(
    prompt_content: str,
    version_label: str,
    model_name: str = "",
    temperature: float = 0.0,
    created_by: str = "system",
    commit_sha: str = "",
) -> str:
    """
    Save a new prompt version. Uploads prompt template to storage and creates
    a version record with metadata.

    Args:
        prompt_content: The full prompt template content (JSON string).
        version_label: Human-readable label (e.g., "v1.2-improved-prompt").
        model_name: Model name associated with this version.
        temperature: Temperature setting for this version.
        created_by: Author of this version (git author).
        commit_sha: Git commit SHA linked to this version.

    Returns:
        JSON string with version_id, s3_path, and timestamp.
    """
    metadata = {
        "model_name": model_name,
        "temperature": temperature,
        "created_by": created_by,
        "commit_sha": commit_sha,
    }
    result = _backend.save_prompt_version(prompt_content, version_label, metadata)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_prompt_version(version_id: str) -> str:
    """
    Retrieve a prompt version by its version_id.

    Args:
        version_id: The UUID of the version to retrieve.

    Returns:
        JSON string with prompt_content, metadata, and created_at.
    """
    try:
        result = _backend.get_prompt_version(version_id)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except FileNotFoundError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def list_versions(limit: int = 20, status_filter: str = "all") -> str:
    """
    List all prompt versions, sorted by creation time (newest first).

    Args:
        limit: Maximum number of versions to return (default: 20).
        status_filter: Filter by status — "all", "active", "promoted", "rolled_back".

    Returns:
        JSON array of version records with version_id, label, created_at, status.
    """
    result = _backend.list_versions(limit=limit, status_filter=status_filter)
    return json.dumps(result, indent=2)


@mcp.tool()
def update_version_status(version_id: str, status: str) -> str:
    """
    Update the status of a stored prompt version.

    Args:
        version_id: The UUID of the version to update.
        status: New status string (e.g. "promoted", "rolled_back", "failed").

    Returns:
        JSON string confirming the update, or an error message.
    """
    try:
        _backend.update_version_status(version_id, status)
        return json.dumps({"ok": True, "version_id": version_id, "status": status})
    except FileNotFoundError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def save_eval_result(
    run_id: str,
    version_id: str,
    scores: str,
    details: str,
) -> str:
    """
    Save evaluation results for a specific run.

    Args:
        run_id: Unique identifier for this evaluation run.
        version_id: The version that was evaluated.
        scores: JSON string with quality_score and breakdown.
        details: JSON string array of per-test-case results.

    Returns:
        JSON string with result_id and timestamp.
    """
    try:
        scores_dict = json.loads(scores)
    except (json.JSONDecodeError, TypeError) as exc:
        return json.dumps({"error": f"Invalid scores JSON: {exc}"})
    try:
        details_list = json.loads(details)
    except (json.JSONDecodeError, TypeError) as exc:
        return json.dumps({"error": f"Invalid details JSON: {exc}"})
    result = _backend.save_eval_result(run_id, version_id, scores_dict, details_list)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_eval_results(
    version_id: str = "",
    run_id: str = "",
) -> str:
    """
    Retrieve evaluation results filtered by version_id or run_id.

    Args:
        version_id: Filter by version (optional).
        run_id: Filter by run (optional).

    Returns:
        JSON array of eval result records.
    """
    result = _backend.get_eval_results(
        version_id=version_id or None,
        run_id=run_id or None,
    )
    return json.dumps(result, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting MCP Storage Server on port %d (streamable-http transport)", _port)
    mcp.run(transport="streamable-http")
