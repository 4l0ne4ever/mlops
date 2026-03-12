"""
Promotion Decision Agent — LangGraph StateGraph that decides promote/rollback/escalate.

State Graph nodes:
    1. receive_report  — parse incoming comparison report from Comparator
    2. apply_rules     — apply decision rules based on verdict
    3. execute_action  — call MCP Deploy / Monitor tools
    4. log_decision    — record decision with reasoning

Decision Matrix:
    | Verdict                  | Decision      | Action                       |
    |--------------------------|---------------|------------------------------|
    | IMPROVED                 | AUTO_PROMOTE  | Deploy v_new to production   |
    | NO_SIGNIFICANT_CHANGE    | NO_ACTION     | Keep v_current               |
    | REGRESSION_DETECTED      | ESCALATE      | Keep v_current, flag v_new   |
    | CRITICAL_REGRESSION      | ROLLBACK      | Rollback to last known good  |
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _atomic_write(path: Path, text: str) -> None:
    """Write *text* to *path* atomically (tmp file + os.replace)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Decision constants
# ---------------------------------------------------------------------------

DECISION_AUTO_PROMOTE = "AUTO_PROMOTE"
DECISION_NO_ACTION = "NO_ACTION"
DECISION_ESCALATE = "ESCALATE"
DECISION_ROLLBACK = "ROLLBACK"

# Map comparator verdict → decision
_VERDICT_TO_DECISION = {
    "IMPROVED": DECISION_AUTO_PROMOTE,
    "NO_SIGNIFICANT_CHANGE": DECISION_NO_ACTION,
    "REGRESSION_DETECTED": DECISION_ESCALATE,
    "CRITICAL_REGRESSION": DECISION_ROLLBACK,
}


class Verdict(str, Enum):
    """Comparator verdict values (str subclass; backward-compatible with plain strings)."""
    IMPROVED = "IMPROVED"
    NO_SIGNIFICANT_CHANGE = "NO_SIGNIFICANT_CHANGE"
    REGRESSION_DETECTED = "REGRESSION_DETECTED"
    CRITICAL_REGRESSION = "CRITICAL_REGRESSION"


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------


class DecisionState(TypedDict, total=False):
    """State passed between Decision Agent nodes."""
    # Input — comparison report from Comparator
    comparison_report: dict[str, Any]
    run_id: str
    v_new_id: str
    v_current_id: str

    # After apply_rules
    decision: str           # AUTO_PROMOTE | NO_ACTION | ESCALATE | ROLLBACK
    reasoning: str          # human-readable explanation
    confidence: str         # "high" | "medium" | "low"

    # After execute_action
    action_result: dict[str, Any]   # deploy/rollback result
    action_taken: str               # description of action performed

    # After log_decision
    decision_id: str               # UUID identifying this decision event
    decision_logged: bool
    notification_sent: bool

    # Errors
    errors: list[str]


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


def receive_report(state: DecisionState) -> dict[str, Any]:
    """
    Node 1: Parse and validate the incoming comparison report.
    """
    report = state.get("comparison_report", {})
    errors = list(state.get("errors", []))

    verdict = report.get("verdict", "")
    if not verdict:
        errors.append("No verdict in comparison report")

    v_new_id = report.get("v_new_id", state.get("v_new_id", ""))
    v_current_id = report.get("v_current_id", state.get("v_current_id", ""))

    logger.info(
        "Decision agent received report: verdict=%s, delta=%.3f",
        verdict,
        report.get("delta", 0.0),
    )

    return {
        "v_new_id": v_new_id,
        "v_current_id": v_current_id,
        "errors": errors,
    }


def apply_rules(state: DecisionState) -> dict[str, Any]:
    """
    Node 2: Apply decision rules based on the comparison verdict.

    Decision logic:
        IMPROVED                 → AUTO_PROMOTE (deploy v_new)
        NO_SIGNIFICANT_CHANGE    → NO_ACTION (keep v_current)
        REGRESSION_DETECTED      → ESCALATE (keep v_current, flag for review)
        CRITICAL_REGRESSION      → ROLLBACK (rollback to last known good)
    """
    report = state.get("comparison_report", {})
    verdict = report.get("verdict", "NO_SIGNIFICANT_CHANGE")
    delta = report.get("delta", 0.0)
    regressions = report.get("regressions", [])
    improvements = report.get("improvements", [])

    decision = _VERDICT_TO_DECISION.get(verdict, DECISION_NO_ACTION)

    # Generate reasoning
    reasoning_parts: list[str] = []

    if decision == DECISION_AUTO_PROMOTE:
        reasoning_parts.append(
            f"Quality score improved by {delta:+.3f} (above auto-promote threshold)."
        )
        if improvements:
            dims = ", ".join(i["dimension"] for i in improvements)
            reasoning_parts.append(f"Improved dimensions: {dims}.")
        confidence = "high"

    elif decision == DECISION_NO_ACTION:
        reasoning_parts.append(
            f"Score delta {delta:+.3f} within tolerance range — no significant change."
        )
        confidence = "medium"

    elif decision == DECISION_ESCALATE:
        reasoning_parts.append(
            f"Overall score dropped by {abs(delta):.3f} (below regression threshold)."
        )
        if regressions:
            worst = min(regressions, key=lambda r: r["delta"])
            reasoning_parts.append(
                f"Worst regression: {worst['dimension']} "
                f"({worst['old']:.1f} → {worst['new']:.1f}, Δ={worst['delta']:+.3f})."
            )
        reasoning_parts.append("Escalating to human review.")
        confidence = "medium"

    elif decision == DECISION_ROLLBACK:
        critical = [
            r for r in regressions
            if r["delta"] < report.get("thresholds_used", {}).get(
                "critical_dimension_threshold", -1.0
            )
        ]
        reasoning_parts.append(
            f"Critical regression detected: {len(critical)} dimension(s) "
            f"below critical threshold."
        )
        for reg in critical:
            reasoning_parts.append(
                f"  - {reg['dimension']}: {reg['old']:.1f} → {reg['new']:.1f} "
                f"(Δ={reg['delta']:+.3f})"
            )
        reasoning_parts.append("Rolling back to protect production quality.")
        confidence = "high"
    else:
        reasoning_parts.append("Unknown verdict — defaulting to NO_ACTION.")
        confidence = "low"

    reasoning = " ".join(reasoning_parts)

    logger.info(
        "Decision: %s (confidence=%s) — %s",
        decision,
        confidence,
        reasoning[:120],
    )

    return {
        "decision": decision,
        "reasoning": reasoning,
        "confidence": confidence,
    }


def execute_action(state: DecisionState) -> dict[str, Any]:
    """
    Node 3: Execute the decided action via MCP Deploy / Monitor tools.
    """
    decision = state.get("decision", DECISION_NO_ACTION)
    v_new_id = state.get("v_new_id", "")
    v_current_id = state.get("v_current_id", "")
    errors = list(state.get("errors", []))

    action_result: dict[str, Any] = {}
    action_taken = ""

    if decision == DECISION_AUTO_PROMOTE:
        # Deploy v_new to production via MCP Deploy server (fallback: local backend)
        try:
            from agents.mcp_client import MCPDeployClient, MCPStorageClient

            deploy_client = MCPDeployClient()
            action_result = deploy_client.deploy_version(v_new_id, "production")
            action_taken = (
                f"Deployed {v_new_id} to production "
                f"(deployment_id={action_result.get('deployment_id', '')})"
            )

            # Update version status to "promoted" via MCP Storage
            try:
                storage_client = MCPStorageClient()
                storage_client.update_version_status(v_new_id, "promoted")
                logger.info("Version %s status updated to 'promoted'", v_new_id)
            except Exception as exc:
                logger.warning("Could not update version status: %s", exc)

        except Exception as exc:
            errors.append(f"Deploy failed: {exc}")
            action_taken = f"Deploy failed: {exc}"
            logger.error("Deploy action failed: %s", exc)

    elif decision == DECISION_ROLLBACK:
        # Rollback to v_current via MCP Deploy server (fallback: local backend)
        try:
            from agents.mcp_client import MCPDeployClient

            deploy_client = MCPDeployClient()
            action_result = deploy_client.rollback_version(v_current_id)
            action_taken = (
                f"Rolled back to {v_current_id} "
                f"(deployment_id={action_result.get('deployment_id', '')})"
            )
        except Exception as exc:
            errors.append(f"Rollback failed: {exc}")
            action_taken = f"Rollback failed: {exc}"
            logger.error("Rollback action failed: %s", exc)

    elif decision == DECISION_ESCALATE:
        action_taken = (
            f"Escalated to human review — "
            f"v_new ({v_new_id}) flagged for manual inspection."
        )
        action_result = {"escalated": True, "v_new_id": v_new_id}

    else:  # NO_ACTION
        action_taken = (
            f"No action taken — keeping current version ({v_current_id})."
        )
        action_result = {"no_action": True}

    logger.info("Action: %s", action_taken)

    return {
        "action_result": action_result,
        "action_taken": action_taken,
        "errors": errors,
    }


def log_decision(state: DecisionState) -> dict[str, Any]:
    """
    Node 4: Log the decision with reasoning to MCP Monitor and local storage.
    """
    decision = state.get("decision", DECISION_NO_ACTION)
    reasoning = state.get("reasoning", "")
    run_id = state.get("run_id", "")
    errors = list(state.get("errors", []))
    _decision_id = str(uuid.uuid4())

    decision_record = {
        "decision_id": _decision_id,
        "run_id": run_id,
        "decision": decision,
        "reasoning": reasoning,
        "confidence": state.get("confidence", ""),
        "v_new_id": state.get("v_new_id", ""),
        "v_current_id": state.get("v_current_id", ""),
        "action_taken": state.get("action_taken", ""),
        "action_result": state.get("action_result", {}),
        "comparison_report": state.get("comparison_report", {}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Log to MCP Monitor (fallback: local backend)
    decision_logged = False
    try:
        from agents.mcp_client import MCPMonitorClient

        monitor = MCPMonitorClient()

        # Push decision metric via MCP
        monitor.push_metric(
            metric_name="decision_event",
            value=1.0,
            dimensions={
                "decision": decision,
                "run_id": run_id,
                "v_new_id": state.get("v_new_id", ""),
            },
        )

        # Write detailed log (local backend; no write_log MCP tool)
        monitor.write_log(
            log_group="decisions",
            message=f"Decision: {decision} — {reasoning[:200]}",
            level="INFO" if decision in (DECISION_AUTO_PROMOTE, DECISION_NO_ACTION)
            else "WARNING",
            extra=decision_record,
        )

        decision_logged = True
        logger.info("Decision logged to monitor: %s", decision)
    except Exception as exc:
        errors.append(f"Monitor logging failed: {exc}")
        logger.warning("Could not log decision to monitor: %s", exc)

    # Save decision to local pipeline-runs
    notification_sent = False
    try:
        data_dir = Path(
            os.environ.get(
                "STORAGE_DATA_DIR", str(_PROJECT_ROOT / ".local-data")
            )
        )
        decisions_dir = data_dir / "decisions"
        decisions_dir.mkdir(parents=True, exist_ok=True)

        decision_path = decisions_dir / f"{run_id or 'manual'}.json"
        _atomic_write(
            decision_path,
            json.dumps(decision_record, indent=2, ensure_ascii=False),
        )

        # Notification simulation (Phase 3 P3-4)
        if decision in (DECISION_ESCALATE, DECISION_ROLLBACK):
            _send_notification(decision, decision_record)
            notification_sent = True
    except Exception as exc:
        errors.append(f"Decision save failed: {exc}")
        logger.warning("Could not save decision: %s", exc)

    return {
        "decision_id": _decision_id,
        "decision_logged": decision_logged,
        "notification_sent": notification_sent,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Notification system (P3-4)
# ---------------------------------------------------------------------------


def _send_notification(decision: str, record: dict[str, Any]) -> None:
    """
    Send alert notification for ESCALATE or ROLLBACK decisions.

    Currently logs to file + structured log. In production, this would
    integrate with Slack webhook, Discord, or email.
    """
    v_new = record.get("v_new_id", "unknown")
    v_current = record.get("v_current_id", "unknown")
    reasoning = record.get("reasoning", "")

    if decision == DECISION_ROLLBACK:
        severity = "CRITICAL"
        subject = f"🚨 Critical Regression — Rolled back to {v_current}"
    else:
        severity = "WARNING"
        subject = f"⚠️ Regression Detected — Escalated for review"

    notification = {
        "severity": severity,
        "subject": subject,
        "body": (
            f"Version: {v_new} vs {v_current}\n"
            f"Decision: {decision}\n"
            f"Reasoning: {reasoning}\n"
            f"Action: {record.get('action_taken', 'N/A')}"
        ),
        "channel": "log",  # Would be "slack" / "email" in production
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Save notification to file
    try:
        data_dir = Path(
            os.environ.get(
                "STORAGE_DATA_DIR", str(_PROJECT_ROOT / ".local-data")
            )
        )
        notif_dir = data_dir / "notifications"
        notif_dir.mkdir(parents=True, exist_ok=True)

        run_id = record.get("run_id", "manual")
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        notif_path = notif_dir / f"{run_id}_{ts}.json"
        _atomic_write(
            notif_path,
            json.dumps(notification, indent=2, ensure_ascii=False),
        )
        logger.info(
            "Notification sent [%s]: %s", severity, subject
        )
    except Exception as exc:
        logger.warning("Notification save failed: %s", exc)


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_decision_graph():
    """
    Build the Promotion Decision LangGraph StateGraph.

    Returns a compiled graph: invoke with {comparison_report, run_id}.
    """
    from langgraph.graph import END, StateGraph

    graph = StateGraph(DecisionState)

    graph.add_node("receive_report", receive_report)
    graph.add_node("apply_rules", apply_rules)
    graph.add_node("execute_action", execute_action)
    graph.add_node("log_decision", log_decision)

    graph.set_entry_point("receive_report")
    graph.add_edge("receive_report", "apply_rules")
    graph.add_edge("apply_rules", "execute_action")
    graph.add_edge("execute_action", "log_decision")
    graph.add_edge("log_decision", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

# Module-level compiled graph — built once on first call.
# LangGraph graph compilation is non-trivial; re-compiling on every
# make_decision() call wastes CPU and adds latency in eval pipelines.
_DECISION_GRAPH: Any = None


def make_decision(
    comparison_report: dict[str, Any],
    run_id: str = "",
) -> dict[str, Any]:
    """
    Run the Decision Agent and return the full decision result.

    Args:
        comparison_report: Output from Version Comparator Agent.
        run_id: Pipeline run ID for tracing.

    Returns:
        Dict with decision, reasoning, action_result, etc.
    """
    global _DECISION_GRAPH
    if _DECISION_GRAPH is None:
        _DECISION_GRAPH = build_decision_graph()

    initial_state: DecisionState = {
        "comparison_report": comparison_report,
        "run_id": run_id,
        "errors": [],
    }

    result = _DECISION_GRAPH.invoke(initial_state)
    return {
        "decision": result.get("decision", DECISION_NO_ACTION),
        "reasoning": result.get("reasoning", ""),
        "confidence": result.get("confidence", ""),
        "action_taken": result.get("action_taken", ""),
        "action_result": result.get("action_result", {}),
        "decision_logged": result.get("decision_logged", False),
        "notification_sent": result.get("notification_sent", False),
        "errors": result.get("errors", []),
    }
