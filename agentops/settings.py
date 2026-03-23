from __future__ import annotations

"""
Centralized runtime settings for the AgentOps platform.

All shared ports, base paths, and data directories should be imported from
this module instead of being duplicated as magic numbers or strings.

Environment variables still take precedence; this module provides a single
place where defaults are defined.
"""

from pathlib import Path
import os

# Package location (after pip install this is site-packages/agentops/../..)
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Ports (overridable via env)
# ---------------------------------------------------------------------------

ORCHESTRATOR_PORT: int = int(os.environ.get("ORCHESTRATOR_PORT", "7000"))
MCP_STORAGE_PORT: int = int(os.environ.get("MCP_STORAGE_PORT", "8000"))
MCP_MONITOR_PORT: int = int(os.environ.get("MCP_MONITOR_PORT", "8001"))
MCP_DEPLOY_PORT: int = int(os.environ.get("MCP_DEPLOY_PORT", "8002"))
TARGET_APP_PROD_PORT: int = int(os.environ.get("TARGET_APP_PROD_PORT", "9000"))
TARGET_APP_STAGING_PORT: int = int(os.environ.get("TARGET_APP_STAGING_PORT", "9001"))
DASHBOARD_PORT: int = int(os.environ.get("DASHBOARD_PORT", "3000"))

# ---------------------------------------------------------------------------
# Paths and directories (fall back to cwd when repo layout not present)
# ---------------------------------------------------------------------------

_REPO_CONFIGS_DIR_DEFAULT: Path = PROJECT_ROOT / "configs"
_PKG_CONFIGS_DIR_DEFAULT: Path = Path(__file__).resolve().parent / "configs"

# Prefer repo configs when developing; otherwise fall back to packaged configs.
CONFIGS_DIR: Path = (
    _REPO_CONFIGS_DIR_DEFAULT
    if _REPO_CONFIGS_DIR_DEFAULT.exists()
    else _PKG_CONFIGS_DIR_DEFAULT
    if _PKG_CONFIGS_DIR_DEFAULT.exists()
    else Path.cwd() / "configs"
)

_REPO_EVAL_DATA_DIR_DEFAULT: Path = PROJECT_ROOT / "eval-datasets"
_PKG_EVAL_DATA_DIR_DEFAULT: Path = Path(__file__).resolve().parent / "eval_datasets"

# Prefer repo eval datasets when developing; otherwise fall back to packaged copies.
EVAL_DATA_DIR: Path = (
    _REPO_EVAL_DATA_DIR_DEFAULT
    if _REPO_EVAL_DATA_DIR_DEFAULT.exists()
    else _PKG_EVAL_DATA_DIR_DEFAULT
    if _PKG_EVAL_DATA_DIR_DEFAULT.exists()
    else Path.cwd() / "eval-datasets"
)

DEFAULT_APP_CONFIG_PATH: Path = Path(
    # If APP_CONFIG is provided relative, resolve it against the project root.
    (
        (lambda v: str((PROJECT_ROOT / v).resolve()) if not Path(v).is_absolute() else v)(
            os.environ.get("APP_CONFIG", "")
        )
    )
    if os.environ.get("APP_CONFIG")
    else str(CONFIGS_DIR / "local.json")
)

_DATA_DIR_DEFAULT: Path = PROJECT_ROOT / ".local-data"
_shared_data_dir: Path = (
    _DATA_DIR_DEFAULT if _DATA_DIR_DEFAULT.exists() else Path.cwd() / ".local-data"
)
STORAGE_DATA_DIR: Path = Path(
    (
        str((PROJECT_ROOT / os.environ["STORAGE_DATA_DIR"]).resolve())
        if os.environ.get("STORAGE_DATA_DIR") and not Path(os.environ["STORAGE_DATA_DIR"]).is_absolute()
        else os.environ.get("STORAGE_DATA_DIR", str(_shared_data_dir))
    )
)
MONITOR_DATA_DIR: Path = Path(
    (
        str((PROJECT_ROOT / os.environ["MONITOR_DATA_DIR"]).resolve())
        if os.environ.get("MONITOR_DATA_DIR") and not Path(os.environ["MONITOR_DATA_DIR"]).is_absolute()
        else os.environ.get("MONITOR_DATA_DIR", str(_shared_data_dir))
    )
)
DEPLOY_DATA_DIR: Path = Path(
    (
        str((PROJECT_ROOT / os.environ["DEPLOY_DATA_DIR"]).resolve())
        if os.environ.get("DEPLOY_DATA_DIR") and not Path(os.environ["DEPLOY_DATA_DIR"]).is_absolute()
        else os.environ.get("DEPLOY_DATA_DIR", str(_shared_data_dir))
    )
)

