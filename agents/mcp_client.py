"""
MCP Client for AgentOps Agents.

Provides helper functions to call MCP Storage and Monitor tools via HTTP/SSE.
Falls back to direct backend access when MCP servers are unavailable.

Usage:
    from agents.mcp_client import MCPStorageClient

    client = MCPStorageClient()
    test_cases = client.load_test_cases("eval-datasets/baseline_v1.json")
    client.save_eval_result(run_id, version_id, scores, details)

The client tries MCP server first (SSE at http://localhost:{port}/sse),
then falls back to direct local storage if unavailable.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MCP_JSON_RPC_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
_RPC_VERSION = "2.0"


def _parse_mcp_response(data: Any) -> Any:
    """
    Parse a JSON-RPC 2.0 or MCP content-block response.

    Handles both:
      - Direct JSON-RPC: {"jsonrpc": "2.0", "id": ..., "result": {"content": [...]}}
      - Legacy content-block: {"content": [{"type": "text", "text": "..."}]}
    """
    if isinstance(data, dict):
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        result = data.get("result", data)
        content = result.get("content") if isinstance(result, dict) else None
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block["text"]
                    try:
                        return json.loads(text)
                    except (json.JSONDecodeError, TypeError):
                        return text
        return result
    return data

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MCPStorageClient:
    """
    Client for MCP Storage server tools.

    Tries to call MCP tools via the MCP server's HTTP API.
    Falls back to direct LocalStorageBackend if server unavailable.
    """

    def __init__(
        self,
        storage_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._storage_url = storage_url or os.environ.get(
            "MCP_STORAGE_URL", "http://localhost:8000"
        )
        self._timeout = timeout
        self._backend = None  # lazy-loaded fallback
        self._http_client: httpx.Client | None = None  # reusable HTTP client

    def _get_fallback_backend(self):
        """Lazy-load the direct storage backend as fallback."""
        if self._backend is None:
            import sys
            sys.path.insert(0, str(_PROJECT_ROOT / "mcp-servers" / "storage"))
            from storage_backend import LocalStorageBackend

            data_dir = os.environ.get(
                "STORAGE_DATA_DIR", str(_PROJECT_ROOT / ".local-data")
            )
            self._backend = LocalStorageBackend(data_dir=data_dir)
            logger.info("Fallback storage backend initialized: %s", data_dir)
        return self._backend

    def _get_http_client(self) -> httpx.Client:
        """Return a reusable httpx.Client (lazy-created)."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.Client(timeout=self._timeout)
        return self._http_client

    def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._http_client is not None and not self._http_client.is_closed:
            self._http_client.close()

    def _call_mcp_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """
        Call an MCP tool via the MCP Streamable-HTTP transport (JSON-RPC 2.0).

        POSTs to ``/mcp`` (the standard FastMCP streamable-http endpoint) with
        a JSON-RPC 2.0 ``tools/call`` request.  The server returns either a
        direct JSON-RPC response or an SSE stream; the ``Accept`` header asks
        for plain JSON so we get a synchronous response body.
        """
        try:
            url = f"{self._storage_url}/mcp"
            payload = {
                "jsonrpc": _RPC_VERSION,
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
            client = self._get_http_client()
            resp = client.post(url, json=payload, headers=_MCP_JSON_RPC_HEADERS)
            if resp.status_code == 200:
                return _parse_mcp_response(resp.json())
            raise Exception(f"MCP call failed: HTTP {resp.status_code}")
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            logger.debug("MCP server unavailable (%s), using fallback", exc)
            raise
        except Exception as exc:
            logger.debug("MCP call error: %s, using fallback", exc)
            raise

    def is_server_available(self) -> bool:
        """Check if MCP Storage server is reachable (streamable-http transport)."""
        try:
            client = self._get_http_client()
            resp = client.get(f"{self._storage_url}/mcp")
            return resp.status_code in (200, 405, 406)  # endpoint exists
        except Exception:
            return False

    def load_test_cases(self, test_suite_path: str) -> list[dict[str, Any]]:
        """
        Load test cases from a JSON file.

        Tries MCP Storage server first, falls back to direct file read.

        Args:
            test_suite_path: Path to test suite JSON file
                (relative to project root or absolute).

        Returns:
            List of test case dicts.
        """
        path = Path(test_suite_path)
        if not path.is_absolute():
            path = _PROJECT_ROOT / path

        if not path.exists():
            raise FileNotFoundError(f"Test suite not found: {path}")

        # For test suite files, direct file read is the correct approach
        # (test suites are local files, not stored via MCP).
        # MCP Storage is for eval results and versions.
        test_cases = json.loads(path.read_text(encoding="utf-8"))
        logger.info(
            "Loaded %d test cases from %s", len(test_cases), path.name
        )
        return test_cases

    def save_eval_result(
        self,
        run_id: str,
        version_id: str,
        scores: dict[str, Any],
        details: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Save evaluation results via MCP Storage.

        Tries MCP server first, falls back to direct backend.

        Args:
            run_id: Unique run identifier.
            version_id: Version that was evaluated.
            scores: Quality score dict with breakdown.
            details: Per-test-case results list.

        Returns:
            Dict with result_id and timestamp.
        """
        # Try MCP server first
        try:
            result = self._call_mcp_tool("save_eval_result", {
                "run_id": run_id,
                "version_id": version_id,
                "scores": json.dumps(scores),
                "details": json.dumps(details, ensure_ascii=False),
            })
            logger.info(
                "Eval result saved via MCP: run_id=%s, result_id=%s",
                run_id,
                result.get("result_id", ""),
            )
            return result
        except Exception as exc:
            logger.info(
                "MCP save failed (%s), using direct backend", type(exc).__name__
            )

        # Fallback to direct backend
        backend = self._get_fallback_backend()
        result = backend.save_eval_result(
            run_id=run_id,
            version_id=version_id,
            scores=scores,
            details=details,
        )
        logger.info(
            "Eval result saved via fallback: run_id=%s, result_id=%s",
            run_id,
            result.get("result_id", ""),
        )
        return result

    def get_eval_results(
        self,
        version_id: str = "",
        run_id: str = "",
    ) -> list[dict[str, Any]]:
        """
        Retrieve evaluation results via MCP Storage.

        Args:
            version_id: Filter by version (optional).
            run_id: Filter by run (optional).

        Returns:
            List of eval result records.
        """
        # Try MCP server first
        try:
            result = self._call_mcp_tool("get_eval_results", {
                "version_id": version_id,
                "run_id": run_id,
            })
            return result if isinstance(result, list) else []
        except Exception:
            pass

        # Fallback to direct backend
        backend = self._get_fallback_backend()
        return backend.get_eval_results(
            version_id=version_id or None,
            run_id=run_id or None,
        )

    def list_versions(
        self,
        limit: int = 20,
        status_filter: str = "all",
    ) -> list[dict[str, Any]]:
        """
        List stored prompt versions via MCP Storage.

        Tries MCP server first, falls back to direct backend.

        Args:
            limit: Maximum number of versions to return.
            status_filter: "all", "promoted", "pending", etc.

        Returns:
            List of version records, newest first.
        """
        try:
            result = self._call_mcp_tool("list_versions", {
                "limit": limit,
                "status_filter": status_filter,
            })
            return result if isinstance(result, list) else []
        except Exception:
            pass

        # Fallback to direct backend
        backend = self._get_fallback_backend()
        return backend.list_versions(limit=limit, status_filter=status_filter)

    def update_version_status(self, version_id: str, status: str) -> dict[str, Any]:
        """
        Update a version's status via MCP Storage.

        Tries MCP server first (``update_version_status`` tool),
        falls back to direct backend.
        """
        try:
            result = self._call_mcp_tool(
                "update_version_status",
                {"version_id": version_id, "status": status},
            )
            if isinstance(result, str):
                result = json.loads(result)
            logger.info("Version %s status → %s via MCP", version_id, status)
            return result if isinstance(result, dict) else {"ok": True}
        except Exception as exc:
            logger.info(
                "MCP update_version_status failed (%s), using direct backend",
                type(exc).__name__,
            )

        # Fallback to direct backend
        backend = self._get_fallback_backend()
        backend.update_version_status(version_id, status)
        logger.info("Version %s status → %s via fallback backend", version_id, status)
        return {"ok": True, "version_id": version_id, "status": status}


class MCPDeployClient:
    """
    Client for MCP Deploy server tools.

    Tries MCP server first (http://localhost:8002/call-tool),
    falls back to LocalDeployBackend.
    """

    def __init__(
        self,
        deploy_url: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._deploy_url = deploy_url or os.environ.get(
            "MCP_DEPLOY_URL", "http://localhost:8002"
        )
        self._timeout = timeout
        self._backend = None
        self._http_client: httpx.Client | None = None

    def _get_fallback_backend(self):
        if self._backend is None:
            import sys
            sys.path.insert(0, str(_PROJECT_ROOT / "mcp-servers" / "deploy"))
            from deploy_backend import LocalDeployBackend

            config_path = os.environ.get(
                "APP_CONFIG", str(_PROJECT_ROOT / "configs" / "local.json")
            )
            try:
                config = json.loads(
                    Path(_PROJECT_ROOT / config_path.lstrip("/")).read_text(encoding="utf-8")
                    if not Path(config_path).is_absolute()
                    else Path(config_path).read_text(encoding="utf-8")
                )
            except (FileNotFoundError, json.JSONDecodeError):
                config = {}

            data_dir = os.environ.get(
                "DEPLOY_DATA_DIR", str(_PROJECT_ROOT / ".local-data")
            )
            self._backend = LocalDeployBackend(data_dir=data_dir, local_config=config)
        return self._backend

    def _get_http_client(self) -> httpx.Client:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.Client(timeout=self._timeout)
        return self._http_client

    def close(self) -> None:
        if self._http_client is not None and not self._http_client.is_closed:
            self._http_client.close()

    def _call_mcp_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        try:
            url = f"{self._deploy_url}/mcp"
            payload = {
                "jsonrpc": _RPC_VERSION,
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
            client = self._get_http_client()
            resp = client.post(url, json=payload, headers=_MCP_JSON_RPC_HEADERS)
            if resp.status_code == 200:
                return _parse_mcp_response(resp.json())
            raise Exception(f"MCP deploy call failed: HTTP {resp.status_code}")
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            logger.debug("MCP deploy server unavailable (%s), using fallback", exc)
            raise
        except Exception as exc:
            logger.debug("MCP deploy call error: %s, using fallback", exc)
            raise

    def deploy_version(self, version_id: str, environment: str = "production") -> dict[str, Any]:
        """Deploy a version. Tries MCP first, falls back to local backend."""
        try:
            result = self._call_mcp_tool("deploy_version", {
                "version_id": version_id,
                "environment": environment,
            })
            if isinstance(result, str):
                result = json.loads(result)
            logger.info("Deployed %s via MCP: %s", version_id, result)
            return result if isinstance(result, dict) else {"deployment_id": str(result)}
        except Exception:
            pass
        backend = self._get_fallback_backend()
        return backend.deploy_version(version_id, environment)

    def rollback_version(self, target_version_id: str) -> dict[str, Any]:
        """Rollback to a previous version. Tries MCP first, falls back to local backend."""
        try:
            result = self._call_mcp_tool("rollback_version", {
                "target_version_id": target_version_id,
            })
            if isinstance(result, str):
                result = json.loads(result)
            logger.info("Rolled back to %s via MCP: %s", target_version_id, result)
            return result if isinstance(result, dict) else {"deployment_id": str(result)}
        except Exception:
            pass
        backend = self._get_fallback_backend()
        return backend.rollback_version(target_version_id)


class MCPMonitorClient:
    """
    Client for MCP Monitor server tools.

    Tries MCP server first (http://localhost:8001/call-tool),
    falls back to LocalMonitorBackend.
    """

    def __init__(
        self,
        monitor_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._monitor_url = monitor_url or os.environ.get(
            "MCP_MONITOR_URL", "http://localhost:8001"
        )
        self._timeout = timeout
        self._backend = None
        self._http_client: httpx.Client | None = None

    def _get_fallback_backend(self):
        if self._backend is None:
            import sys
            sys.path.insert(0, str(_PROJECT_ROOT / "mcp-servers" / "monitor"))
            from monitor_backend import LocalMonitorBackend

            data_dir = os.environ.get(
                "MONITOR_DATA_DIR", str(_PROJECT_ROOT / ".local-data")
            )
            self._backend = LocalMonitorBackend(data_dir=data_dir)
        return self._backend

    def _get_http_client(self) -> httpx.Client:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.Client(timeout=self._timeout)
        return self._http_client

    def close(self) -> None:
        if self._http_client is not None and not self._http_client.is_closed:
            self._http_client.close()

    def _call_mcp_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        try:
            url = f"{self._monitor_url}/mcp"
            payload = {
                "jsonrpc": _RPC_VERSION,
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
            client = self._get_http_client()
            resp = client.post(url, json=payload, headers=_MCP_JSON_RPC_HEADERS)
            if resp.status_code == 200:
                return _parse_mcp_response(resp.json())
            raise Exception(f"MCP monitor call failed: HTTP {resp.status_code}")
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            logger.debug("MCP monitor server unavailable (%s), using fallback", exc)
            raise
        except Exception as exc:
            logger.debug("MCP monitor call error: %s, using fallback", exc)
            raise

    def push_metric(
        self,
        metric_name: str,
        value: float,
        dimensions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Push a metric. Tries MCP first, falls back to LocalMonitorBackend."""
        dims = dimensions or {}
        try:
            result = self._call_mcp_tool("push_metric", {
                "metric_name": metric_name,
                "value": value,
                "version_id": dims.get("version_id", ""),
                "environment": dims.get("environment", ""),
            })
            if isinstance(result, str):
                result = json.loads(result)
            return result if isinstance(result, dict) else {"status": "ok"}
        except Exception:
            pass
        backend = self._get_fallback_backend()
        return backend.push_metric(metric_name, value, dims)

    def write_log(
        self,
        log_group: str,
        message: str,
        level: str = "INFO",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Write a log entry. MCP server has no write_log tool; uses local backend."""
        backend = self._get_fallback_backend()
        backend.write_log(log_group=log_group, message=message, level=level, extra=extra or {})

