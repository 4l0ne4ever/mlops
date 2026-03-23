"""
MCP Server: Monitor — metrics, logs, and health checks.

Exposes 4 MCP tools via the **streamable-http** `/mcp` endpoint:
  - push_metric: record a custom metric datapoint
  - get_metrics: retrieve metric history
  - get_logs: retrieve log entries with optional filter
  - check_health: probe a target app endpoint

Run:
    python mcp-servers/monitor/server.py

Streamable HTTP endpoint:
    POST http://localhost:8001/mcp

Use the standard streamable-http MCP handshake as documented in
`docs/mcp-integration-guide.md`.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Ensure project root (with agentops package) is importable when running this
# file directly (e.g. `python mcp-servers/monitor/server.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agentops.settings import PROJECT_ROOT, MONITOR_DATA_DIR, MCP_MONITOR_PORT

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

_PROJECT_ROOT = PROJECT_ROOT
_env_path = _PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

_data_dir = str(MONITOR_DATA_DIR)

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    stream=sys.stdout,
)
logger = logging.getLogger("agentops.mcp-monitor")

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

from mcp_servers.monitor.monitor_backend import LocalMonitorBackend

_backend = LocalMonitorBackend(data_dir=_data_dir)

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

_port = MCP_MONITOR_PORT
mcp = FastMCP("agentops-monitor", port=_port)


@mcp.tool()
def push_metric(
    metric_name: str,
    value: float,
    version_id: str = "",
    environment: str = "",
) -> str:
    """
    Record a custom metric datapoint. Simulates CloudWatch PutMetricData.

    Args:
        metric_name: Name of the metric (e.g., "QualityScore", "EvalRunDuration").
        value: Numeric value for the metric.
        version_id: Version associated with this metric (optional dimension).
        environment: Environment — "staging" or "production" (optional dimension).

    Returns:
        JSON string with status and timestamp.
    """
    dimensions: dict[str, str] = {}
    if version_id:
        dimensions["version_id"] = version_id
    if environment:
        dimensions["environment"] = environment

    result = _backend.push_metric(metric_name, value, dimensions)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_metrics(
    metric_name: str,
    version_id: str = "",
    time_range: str = "last_24h",
) -> str:
    """
    Retrieve metric datapoints from history.

    Args:
        metric_name: Name of the metric to retrieve.
        version_id: Filter by version_id dimension (optional).
        time_range: Time range to query — "last_1h", "last_24h", "last_7d" (default: last_24h).

    Returns:
        JSON array of datapoints [{timestamp, value}, ...].
    """
    result = _backend.get_metrics(
        metric_name=metric_name,
        version_id=version_id,
        time_range=time_range,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def get_logs(
    log_group: str,
    filter_pattern: str = "",
    time_range: str = "last_24h",
) -> str:
    """
    Retrieve log entries from a log group, optionally filtered by a pattern.

    Args:
        log_group: Name of the log group (e.g., "pipeline-runs", "decisions").
        filter_pattern: Text pattern to filter log entries (optional).
        time_range: Time range — "last_1h", "last_24h", "last_7d" (default: last_24h).

    Returns:
        JSON array of log entries, newest first.
    """
    result = _backend.get_logs(
        log_group=log_group,
        filter_pattern=filter_pattern,
        time_range=time_range,
    )
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def check_health(endpoint_url: str) -> str:
    """
    Check the health of a target application endpoint.

    Sends an HTTP GET request to the endpoint and reports status,
    response time, and any errors.

    Args:
        endpoint_url: Full URL to probe (e.g., "http://localhost:9000/health").

    Returns:
        JSON string with status, response_time_ms, and timestamp.
    """
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        start = time.perf_counter()
        with httpx.Client(timeout=10.0) as client:
            response = client.get(endpoint_url)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        result = {
            "status": "healthy" if response.status_code == 200 else "unhealthy",
            "status_code": response.status_code,
            "response_time_ms": elapsed_ms,
            "timestamp": timestamp,
        }
    except httpx.TimeoutException:
        result = {
            "status": "timeout",
            "response_time_ms": 10000,
            "timestamp": timestamp,
            "error": "Connection timed out after 10s",
        }
    except httpx.ConnectError as exc:
        result = {
            "status": "unreachable",
            "response_time_ms": 0,
            "timestamp": timestamp,
            "error": f"Connection refused: {exc}",
        }
    except Exception as exc:
        result = {
            "status": "error",
            "response_time_ms": 0,
            "timestamp": timestamp,
            "error": str(exc),
        }

    # Also log the health check to monitor backend
    _backend.write_log(
        log_group="health-checks",
        message=f"Health check {endpoint_url}: {result['status']}",
        level="INFO" if result["status"] == "healthy" else "WARNING",
        extra={"endpoint": endpoint_url, **result},
    )

    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting MCP Monitor Server on port %d (streamable-http transport)", _port)
    mcp.run(transport="streamable-http")
