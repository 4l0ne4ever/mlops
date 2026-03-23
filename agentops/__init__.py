"""
Public framework surface for AgentOps.

The goal is to provide a small set of stable, importable symbols:
  - `agentops.configure()` / `agentops.get_config()`
  - core agents: `agentops.Orchestrator`, `agentops.EvalRunner`
  - scoring/judge: `agentops.QualityScoreCalculator`, `agentops.LLMJudgeEvaluator`
  - MCP helpers: `agentops.mcp.*`
  - local backends: `agentops.backends.*`
  - bundled reference app: `agentops.target_app.*`
"""

from __future__ import annotations

from .config import configure, get_config, AgentOpsConfig
from .core import EvalRunner, Orchestrator, QualityScoreCalculator, LLMJudgeEvaluator
from .mcp import StorageClient, DeployClient, MonitorClient, call_tool
from .backends.interfaces import StorageBackend, MonitorBackend, DeployBackend
from . import target_app

__all__ = [
    "AgentOpsConfig",
    "configure",
    "get_config",
    "Orchestrator",
    "EvalRunner",
    "QualityScoreCalculator",
    "LLMJudgeEvaluator",
    "StorageClient",
    "DeployClient",
    "MonitorClient",
    "call_tool",
    "StorageBackend",
    "MonitorBackend",
    "DeployBackend",
    "LocalStorageBackend",
    "LocalMonitorBackend",
    "LocalDeployBackend",
    "target_app",
]


def __getattr__(name: str):
    # Lazy imports so `import agentops` works from source without requiring the
    # setuptools package-dir alias to be active.
    if name == "LocalStorageBackend":
        from .backends.storage_local import LocalStorageBackend

        return LocalStorageBackend
    if name == "LocalMonitorBackend":
        from .backends.monitor_local import LocalMonitorBackend

        return LocalMonitorBackend
    if name == "LocalDeployBackend":
        from .backends.deploy_local import LocalDeployBackend

        return LocalDeployBackend
    raise AttributeError(f"module 'agentops' has no attribute {name!r}")

