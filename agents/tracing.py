"""
LangSmith Tracing Configuration for AgentOps Agents.

This module provides centralized tracing setup for all LangGraph agents.
LangSmith tracing is a Phase 2 DoD requirement: "LangSmith traces visible cho toàn bộ flow".

Usage:
    from agents.tracing import configure_tracing, get_tracer_callbacks

    configure_tracing()  # Call once at startup
    callbacks = get_tracer_callbacks(run_name="eval-run-xxx")
    graph.invoke(state, config={"callbacks": callbacks})

Environment variables (from .env):
    LANGSMITH_API_KEY   — API key from smith.langchain.com
    LANGSMITH_TRACING   — "true" to enable (default: true)
    LANGSMITH_PROJECT   — project name (default: agentops)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_tracing_configured = False


def configure_tracing() -> bool:
    """
    Configure LangSmith tracing from environment variables.

    Loads .env if not yet loaded, sets LANGCHAIN_TRACING_V2 etc.
    Returns True if tracing is enabled, False otherwise.
    """
    global _tracing_configured
    if _tracing_configured:
        return os.environ.get("LANGCHAIN_TRACING_V2") == "true"

    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")

    # Map LANGSMITH_ vars → LANGCHAIN_ vars (LangSmith SDK reads LANGCHAIN_ prefix)
    tracing_enabled = os.environ.get("LANGSMITH_TRACING", "true").lower() == "true"
    api_key = os.environ.get("LANGSMITH_API_KEY", "")
    project = os.environ.get("LANGSMITH_PROJECT", "agentops")

    if tracing_enabled and api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = api_key
        os.environ["LANGCHAIN_PROJECT"] = project
        logger.info(
            "LangSmith tracing ENABLED — project=%s", project
        )
        _tracing_configured = True
        return True
    elif tracing_enabled and not api_key:
        # Tracing requested but no API key — disable gracefully
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        logger.warning(
            "LangSmith tracing requested but LANGSMITH_API_KEY not set — tracing DISABLED"
        )
        _tracing_configured = True
        return False
    else:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        logger.info("LangSmith tracing DISABLED by configuration")
        _tracing_configured = True
        return False


def get_tracer_callbacks(
    run_name: str = "",
    tags: list[str] | None = None,
    metadata: dict | None = None,
) -> list:
    """
    Get LangSmith callback handlers for a graph invocation.

    Args:
        run_name: Human-readable name for the trace (e.g., "eval-run-abc123").
        tags: Optional tags for filtering traces (e.g., ["eval", "v1.2"]).
        metadata: Optional metadata dict attached to the trace.

    Returns:
        List of callback handlers. Empty list if tracing is disabled.
    """
    if os.environ.get("LANGCHAIN_TRACING_V2") != "true":
        return []

    try:
        from langsmith import Client
        from langchain_core.tracers import LangChainTracer

        client = Client()
        tracer = LangChainTracer(
            client=client,
            project_name=os.environ.get("LANGCHAIN_PROJECT", "agentops"),
        )

        # Attach run metadata if provided
        if run_name:
            tracer.run_name = run_name

        return [tracer]
    except ImportError:
        logger.warning("langsmith or langchain_core not installed — tracing disabled")
        return []
    except Exception as exc:
        logger.warning("Failed to create LangSmith tracer: %s", exc)
        return []


def get_graph_config(
    run_name: str = "",
    tags: list[str] | None = None,
    metadata: dict | None = None,
) -> dict:
    """
    Build a LangGraph config dict with tracing callbacks.

    This is the main entry point for agents — pass the returned dict
    as the `config` argument to `graph.invoke(state, config=...)`.

    Args:
        run_name: Name for the LangSmith trace.
        tags: Optional tags for trace filtering.
        metadata: Optional metadata for the trace.

    Returns:
        Config dict suitable for graph.invoke().
    """
    config: dict = {}

    callbacks = get_tracer_callbacks(
        run_name=run_name, tags=tags, metadata=metadata
    )
    if callbacks:
        config["callbacks"] = callbacks

    if tags:
        config["tags"] = tags

    if metadata:
        config["metadata"] = metadata

    if run_name:
        config["run_name"] = run_name

    return config


def is_tracing_enabled() -> bool:
    """Check if LangSmith tracing is currently enabled."""
    return os.environ.get("LANGCHAIN_TRACING_V2") == "true"
