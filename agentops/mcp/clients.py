from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .http_client import McpServerName, call_tool
from ..config import get_config
from ..settings import STORAGE_DATA_DIR, MONITOR_DATA_DIR, DEPLOY_DATA_DIR
from ..backends.storage_local import LocalStorageBackend
from ..backends.monitor_local import LocalMonitorBackend
from ..backends.deploy_local import LocalDeployBackend


def _load_local_deploy_config() -> dict[str, Any]:
    """
    LocalDeployBackend expects the `target_app` URLs from APP_CONFIG.
    """
    import json

    app_cfg_path = os.environ.get("APP_CONFIG")
    if not app_cfg_path:
        return {}
    try:
        return json.loads(Path(app_cfg_path).read_text(encoding="utf-8"))
    except Exception:
        return {}


@dataclass
class MCPClientConfig:
    storage_url: str
    monitor_url: str
    deploy_url: str


def _default_config() -> MCPClientConfig:
    return MCPClientConfig(
        storage_url=os.environ.get("MCP_STORAGE_URL", "http://localhost:8000"),
        monitor_url=os.environ.get("MCP_MONITOR_URL", "http://localhost:8001"),
        deploy_url=os.environ.get("MCP_DEPLOY_URL", "http://localhost:8002"),
    )


class StorageClient:
    def __init__(self, *, config: MCPClientConfig | None = None) -> None:
        self._cfg = config or _default_config()
        self._backend = get_config().backend

    def load_test_cases(self, test_suite_path: str) -> list[dict[str, Any]]:
        # Framework intentionally keeps test suites as local files.
        from pathlib import Path

        p = Path(test_suite_path)
        if not p.is_absolute():
            # Allow relative paths from working directory; full normalization is in later steps.
            p = Path.cwd() / test_suite_path
        return json.loads(p.read_text(encoding="utf-8"))

    def list_versions(self, limit: int = 20, status_filter: str = "all") -> list[dict[str, Any]]:
        if self._backend == "local":
            backend = LocalStorageBackend(data_dir=str(STORAGE_DATA_DIR))
            return backend.list_versions(limit=limit, status_filter=status_filter)

        raise NotImplementedError("Only backend='local' is supported for StorageClient methods yet.")

    def get_eval_results(self, *, version_id: str = "", run_id: str = "") -> list[dict[str, Any]]:
        if self._backend == "local":
            backend = LocalStorageBackend(data_dir=str(STORAGE_DATA_DIR))
            return backend.get_eval_results(
                version_id=version_id or None, run_id=run_id or None
            )

        raise NotImplementedError("Only backend='local' is supported for StorageClient methods yet.")

    def save_eval_result(
        self,
        *,
        run_id: str,
        version_id: str,
        scores: dict[str, Any],
        details: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self._backend == "local":
            backend = LocalStorageBackend(data_dir=str(STORAGE_DATA_DIR))
            return backend.save_eval_result(
                run_id=run_id,
                version_id=version_id,
                scores=scores,
                details=details,
            )

        raise NotImplementedError("Only backend='local' is supported for StorageClient methods yet.")

    def update_version_status(self, version_id: str, status: str) -> dict[str, Any]:
        if self._backend == "local":
            backend = LocalStorageBackend(data_dir=str(STORAGE_DATA_DIR))
            backend.update_version_status(version_id, status)
            return {"ok": True, "version_id": version_id, "status": status}

        raise NotImplementedError("Only backend='local' is supported for StorageClient methods yet.")


class MonitorClient:
    def __init__(self, *, config: MCPClientConfig | None = None) -> None:
        self._cfg = config or _default_config()
        self._backend = get_config().backend

    def push_metric(
        self,
        *,
        metric_name: str,
        value: float,
        dimensions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if self._backend == "local":
            dims = dimensions or {}
            backend = LocalMonitorBackend(data_dir=str(MONITOR_DATA_DIR))
            return backend.push_metric(metric_name, value, dims)

        dims = dimensions or {}
        raise NotImplementedError("Only backend='local' is supported for MonitorClient methods yet.")

    def write_log(
        self,
        *,
        log_group: str,
        message: str,
        level: str = "INFO",
        extra: dict[str, Any] | None = None,
    ) -> None:
        if self._backend == "local":
            backend = LocalMonitorBackend(data_dir=str(MONITOR_DATA_DIR))
            backend.write_log(
                log_group=log_group,
                message=message,
                level=level,
                extra=extra or {},
            )
            return

        # MCP monitor server has no `write_log` tool in this repo.
        raise NotImplementedError(
            "MonitorClient.write_log over MCP is not available in this implementation. "
            "Use backend='local' or write logs via your own MCP server."
        )


class DeployClient:
    def __init__(self, *, config: MCPClientConfig | None = None) -> None:
        self._cfg = config or _default_config()
        self._backend = get_config().backend

    def deploy_version(self, *, version_id: str, environment: str = "production") -> dict[str, Any]:
        if self._backend == "local":
            backend = LocalDeployBackend(
                data_dir=str(DEPLOY_DATA_DIR), local_config=_load_local_deploy_config()
            )
            return backend.deploy_version(version_id, environment)

        raise NotImplementedError("Only backend='local' is supported for DeployClient methods yet.")

    def rollback_version(self, *, target_version_id: str) -> dict[str, Any]:
        if self._backend == "local":
            backend = LocalDeployBackend(
                data_dir=str(DEPLOY_DATA_DIR), local_config=_load_local_deploy_config()
            )
            return backend.rollback_version(target_version_id)

        raise NotImplementedError("Only backend='local' is supported for DeployClient methods yet.")

    def get_deployment_status(
        self,
        *,
        deployment_id: str = "",
        environment: str = "",
    ) -> dict[str, Any]:
        if self._backend == "local":
            backend = LocalDeployBackend(
                data_dir=str(DEPLOY_DATA_DIR), local_config=_load_local_deploy_config()
            )
            return backend.get_deployment_status(deployment_id=deployment_id, environment=environment)

        raise NotImplementedError("Only backend='local' is supported for DeployClient methods yet.")


__all__ = ["StorageClient", "MonitorClient", "DeployClient"]

