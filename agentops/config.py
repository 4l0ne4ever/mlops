from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .settings import (
    PROJECT_ROOT,
    CONFIGS_DIR,
    DEFAULT_APP_CONFIG_PATH,
    STORAGE_DATA_DIR,
    MONITOR_DATA_DIR,
    DEPLOY_DATA_DIR,
    EVAL_DATA_DIR,
)


BackendChoice = Literal["local", "aws"]
TriggerType = Literal["manual", "webhook"]


@dataclass(frozen=True)
class AgentOpsConfig:
    """
    Runtime configuration for the public agentops framework.

    This is a lightweight layer on top of the environment variables and
    config-file conventions used by the current internal implementation.
    """

    target_app_url: str
    test_suite_path: str
    backend: BackendChoice = "local"

    # MCP endpoints (base URLs WITHOUT /mcp)
    mcp_storage_url: str = "http://localhost:8000"
    mcp_monitor_url: str = "http://localhost:8001"
    mcp_deploy_url: str = "http://localhost:8002"

    # Optional persistent data dirs for local backends
    storage_data_dir: str | None = None
    monitor_data_dir: str | None = None
    deploy_data_dir: str | None = None

    # Optional: let users bring their own APP_CONFIG JSON file (target-app + orchestrator + deploy backend)
    app_config_path: str | None = None


_RUNTIME_CONFIG: AgentOpsConfig | None = None


def _resolve_path(path: str | os.PathLike[str]) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p


def _ensure_app_config_file(cfg: AgentOpsConfig) -> Path:
    """
    Create a minimal APP_CONFIG JSON file if the user didn't provide one.

    Internal code expects a JSON file with at least:
      - environment
      - logging.level
      - target_app.production_url
      - target_app.staging_url
    """
    if cfg.app_config_path:
        return _resolve_path(cfg.app_config_path)

    runtime_dir = Path(STORAGE_DATA_DIR) / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    app_config_path = runtime_dir / "app_config.json"

    payload = {
        "environment": "local",
        "logging": {"level": "INFO"},
        "target_app": {
            "production_url": "http://localhost:9000",
            "staging_url": cfg.target_app_url,
        },
        "mcp_servers": {
            "storage": cfg.mcp_storage_url,
            "monitor": cfg.mcp_monitor_url,
            "deploy": cfg.mcp_deploy_url,
        },
        # Keep a minimal shape; other keys are optional for local operation.
        "cors": {"allowed_origins": ["http://localhost:3000"]},
    }

    app_config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return app_config_path


def _resolve_test_suite_path(path: str) -> str:
    """
    Resolve repo-relative eval dataset paths for installed users.

    Examples:
      - "eval-datasets/baseline_v1.json" -> <EVAL_DATA_DIR>/baseline_v1.json
      - "baseline_v1.json" -> <EVAL_DATA_DIR>/baseline_v1.json (if it exists)
    """
    p = Path(path)
    if p.is_absolute():
        return str(p)

    as_str = str(path)
    if as_str.startswith("eval-datasets/"):
        rel = as_str.split("/", 1)[1]
        candidate = EVAL_DATA_DIR / rel
        return str(candidate) if candidate.exists() else str(candidate)

    # If the file exists relative to current working dir, keep it.
    if p.exists():
        return str(p.resolve())

    # Fall back to bundled dataset by filename.
    candidate = EVAL_DATA_DIR / p.name
    return str(candidate)


def configure(
    *,
    target_app_url: str = "http://localhost:9000",
    test_suite_path: str = "eval-datasets/baseline_v1.json",
    backend: BackendChoice = "local",
    mcp_storage_url: str = "http://localhost:8000",
    mcp_monitor_url: str = "http://localhost:8001",
    mcp_deploy_url: str = "http://localhost:8002",
    storage_data_dir: str | None = None,
    monitor_data_dir: str | None = None,
    deploy_data_dir: str | None = None,
    app_config_path: str | None = None,
) -> None:
    """
    Configure agentops runtime.

    This function sets environment variables used by the current internal
    implementation and stores a runtime config in-memory for later wrappers.
    """
    global _RUNTIME_CONFIG

    cfg = AgentOpsConfig(
        target_app_url=target_app_url,
        test_suite_path=_resolve_test_suite_path(test_suite_path),
        backend=backend,
        mcp_storage_url=mcp_storage_url,
        mcp_monitor_url=mcp_monitor_url,
        mcp_deploy_url=mcp_deploy_url,
        storage_data_dir=storage_data_dir,
        monitor_data_dir=monitor_data_dir,
        deploy_data_dir=deploy_data_dir,
        app_config_path=app_config_path,
    )
    _RUNTIME_CONFIG = cfg

    # Set MCP URLs (base URL, client code appends /mcp)
    os.environ["MCP_STORAGE_URL"] = mcp_storage_url
    os.environ["MCP_MONITOR_URL"] = mcp_monitor_url
    os.environ["MCP_DEPLOY_URL"] = mcp_deploy_url

    # Set local data dirs if provided
    if storage_data_dir:
        os.environ["STORAGE_DATA_DIR"] = storage_data_dir
    if monitor_data_dir:
        os.environ["MONITOR_DATA_DIR"] = monitor_data_dir
    if deploy_data_dir:
        os.environ["DEPLOY_DATA_DIR"] = deploy_data_dir

    # Ensure APP_CONFIG exists (used by orchestrator + deploy backend + target app)
    app_cfg_path = _ensure_app_config_file(cfg)
    os.environ["APP_CONFIG"] = str(app_cfg_path)


def get_config() -> AgentOpsConfig:
    """Return the last configured AgentOpsConfig, or a best-effort default."""
    if _RUNTIME_CONFIG is not None:
        return _RUNTIME_CONFIG

    # Best-effort default based on current settings/env.
    inferred_app_config = os.environ.get("APP_CONFIG")
    if inferred_app_config:
        app_cfg_path = _resolve_path(inferred_app_config)
        try:
            data = json.loads(app_cfg_path.read_text(encoding="utf-8"))
            target_app_url = data.get("target_app", {}).get("staging_url", "http://localhost:9001")
        except Exception:
            target_app_url = "http://localhost:9001"
    else:
        target_app_url = "http://localhost:9001"

    return AgentOpsConfig(
        target_app_url=target_app_url,
        test_suite_path=_resolve_test_suite_path("eval-datasets/baseline_v1.json"),
        backend="local",
    )

