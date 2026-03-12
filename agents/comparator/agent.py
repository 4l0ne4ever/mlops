"""
Version Comparator Agent — LangGraph StateGraph that compares v_new vs v_current.

State Graph nodes:
    1. fetch_scores      — load eval results for both versions from MCP Storage
    2. compare_dimensions — per-dimension delta calculation
    3. detect_regression  — classify verdict using configurable thresholds
    4. generate_report    — produce structured comparison report

The Comparator:
    - Receives version IDs and their eval scores
    - Computes per-dimension deltas (task_completion, output_quality, latency, cost)
    - Detects regressions using thresholds from configs/thresholds.json
    - Produces a structured comparison report with verdict

Verdicts:
    - CRITICAL_REGRESSION : any single dimension Δ < critical_dimension_threshold
    - REGRESSION_DETECTED : overall score Δ < overall_regression_threshold
    - IMPROVED            : overall score Δ > auto_promote_threshold
    - NO_SIGNIFICANT_CHANGE : everything else
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Default thresholds (overridden by configs/thresholds.json)
# ---------------------------------------------------------------------------

_DEFAULT_THRESHOLDS = {
    "overall_regression_threshold": -0.5,
    "critical_dimension_threshold": -1.0,
    "auto_promote_threshold": 0.3,
}

# Dimension weights — used only for informational reporting
_DIMENSION_KEYS = [
    "task_completion",
    "output_quality",
    "latency",
    "cost_efficiency",
]


class Verdict(str, Enum):
    """Comparator verdict values (str subclass; backward-compatible with plain strings)."""
    CRITICAL_REGRESSION = "CRITICAL_REGRESSION"
    REGRESSION_DETECTED = "REGRESSION_DETECTED"
    IMPROVED = "IMPROVED"
    NO_SIGNIFICANT_CHANGE = "NO_SIGNIFICANT_CHANGE"


def _coerce_float(value: Any) -> float:
    """Coerce a score value to float.

    DynamoDB and some serializers may return Decimal, string, or a dict like
    ``{"score": 0.85, "weight": 0.25}`` — extract the numeric value safely.
    """
    if isinstance(value, dict):
        value = value.get("score", value.get("value", 0.0))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_breakdown(raw: Any) -> dict[str, Any]:
    """Parse ``score_breakdown`` from string, dict, or None into a plain dict."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _load_thresholds(path: str | Path | None = None) -> dict[str, Any]:
    """Load thresholds from config file, falling back to defaults."""
    if path is None:
        path = _PROJECT_ROOT / "configs" / "thresholds.json"
    path = Path(path)
    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            return {**_DEFAULT_THRESHOLDS, **config}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load thresholds (%s), using defaults", exc)
    return dict(_DEFAULT_THRESHOLDS)


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------


class ComparatorState(TypedDict, total=False):
    """State passed between Comparator nodes."""
    # Input
    v_new_id: str
    v_current_id: str
    v_new_scores: dict[str, Any]       # pre-loaded or fetched
    v_current_scores: dict[str, Any]    # pre-loaded or fetched

    # After fetch_scores
    v_new_quality_score: float
    v_current_quality_score: float
    v_new_breakdown: dict[str, float]
    v_current_breakdown: dict[str, float]

    # After compare_dimensions
    deltas: dict[str, float]           # per-dimension deltas
    overall_delta: float

    # After detect_regression
    verdict: str                       # CRITICAL_REGRESSION | REGRESSION_DETECTED | IMPROVED | NO_SIGNIFICANT_CHANGE
    regressions: list[dict[str, Any]]
    improvements: list[dict[str, Any]]

    # After generate_report
    comparison_report: dict[str, Any]  # full structured report

    # Thresholds
    thresholds: dict[str, Any]

    # Errors
    errors: list[str]


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


def fetch_scores(state: ComparatorState) -> dict[str, Any]:
    """
    Node 1: Load eval scores for both versions.

    If v_new_scores / v_current_scores are already in state (passed from
    the orchestrator), use those directly. Otherwise, fetch from MCP Storage.
    """
    errors = list(state.get("errors", []))

    # Load thresholds
    thresholds = _load_thresholds()

    v_new_scores = state.get("v_new_scores", {})
    v_current_scores = state.get("v_current_scores", {})

    # If scores not pre-loaded, try MCP Storage
    if not v_new_scores or not v_current_scores:
        try:
            from agents.mcp_client import MCPStorageClient
            client = MCPStorageClient()

            if not v_new_scores:
                results = client.get_eval_results(
                    version_id=state.get("v_new_id", "")
                )
                if results:
                    v_new_scores = results[0]  # most recent
                else:
                    errors.append(
                        f"No eval results for v_new={state.get('v_new_id', '')}"
                    )

            if not v_current_scores:
                results = client.get_eval_results(
                    version_id=state.get("v_current_id", "")
                )
                if results:
                    v_current_scores = results[0]
                else:
                    errors.append(
                        f"No eval results for v_current={state.get('v_current_id', '')}"
                    )
        except Exception as exc:
            errors.append(f"Failed to fetch scores: {exc}")

    # Extract quality scores and breakdowns, normalising types from any backend
    v_new_quality = _coerce_float(v_new_scores.get("quality_score", 0.0))
    v_current_quality = _coerce_float(v_current_scores.get("quality_score", 0.0))

    v_new_breakdown = _coerce_breakdown(v_new_scores.get("score_breakdown", {}))
    v_current_breakdown = _coerce_breakdown(v_current_scores.get("score_breakdown", {}))

    logger.info(
        "Scores fetched: v_new=%.3f, v_current=%.3f",
        v_new_quality,
        v_current_quality,
    )

    return {
        "v_new_scores": v_new_scores,
        "v_current_scores": v_current_scores,
        "v_new_quality_score": v_new_quality,
        "v_current_quality_score": v_current_quality,
        "v_new_breakdown": v_new_breakdown,
        "v_current_breakdown": v_current_breakdown,
        "thresholds": thresholds,
        "errors": errors,
    }


def compare_dimensions(state: ComparatorState) -> dict[str, Any]:
    """
    Node 2: Calculate per-dimension deltas between v_new and v_current.

    Positive delta = improvement, negative = regression.
    """
    v_new_breakdown = state.get("v_new_breakdown", {})
    v_current_breakdown = state.get("v_current_breakdown", {})
    v_new_quality = state.get("v_new_quality_score", 0.0)
    v_current_quality = state.get("v_current_quality_score", 0.0)

    deltas: dict[str, float] = {}
    for dim in _DIMENSION_KEYS:
        new_val = v_new_breakdown.get(dim, 0.0)
        current_val = v_current_breakdown.get(dim, 0.0)
        # Breakdown entries may be dicts {score, weight, raw_value} from
        # QualityScoreCalculator.to_dict(); extract the numeric score.
        if isinstance(new_val, dict):
            new_val = new_val.get("score", 0.0)
        if isinstance(current_val, dict):
            current_val = current_val.get("score", 0.0)
        deltas[dim] = round(float(new_val) - float(current_val), 4)

    overall_delta = round(v_new_quality - v_current_quality, 4)

    logger.info(
        "Deltas: overall=%.3f, dims=%s",
        overall_delta,
        {k: f"{v:+.3f}" for k, v in deltas.items()},
    )

    return {
        "deltas": deltas,
        "overall_delta": overall_delta,
    }


def detect_regression(state: ComparatorState) -> dict[str, Any]:
    """
    Node 3: Classify the comparison verdict using threshold-based rules.

    Priority order:
      1. CRITICAL_REGRESSION — any dimension Δ < critical_dimension_threshold
      2. REGRESSION_DETECTED — overall Δ < overall_regression_threshold
      3. IMPROVED           — overall Δ > auto_promote_threshold
      4. NO_SIGNIFICANT_CHANGE — everything else
    """
    deltas = state.get("deltas", {})
    overall_delta = state.get("overall_delta", 0.0)
    thresholds = state.get("thresholds", _DEFAULT_THRESHOLDS)
    v_new_breakdown = state.get("v_new_breakdown", {})
    v_current_breakdown = state.get("v_current_breakdown", {})

    critical_threshold = thresholds.get("critical_dimension_threshold", -1.0)
    overall_threshold = thresholds.get("overall_regression_threshold", -0.5)
    promote_threshold = thresholds.get("auto_promote_threshold", 0.3)

    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []

    for dim, delta in deltas.items():
        old_val = v_current_breakdown.get(dim, 0.0)
        new_val = v_new_breakdown.get(dim, 0.0)
        if isinstance(old_val, dict):
            old_val = old_val.get("score", 0.0)
        if isinstance(new_val, dict):
            new_val = new_val.get("score", 0.0)
        entry = {
            "dimension": dim,
            "old": float(old_val),
            "new": float(new_val),
            "delta": delta,
        }
        if delta < 0:
            regressions.append(entry)
        elif delta > 0:
            improvements.append(entry)

    # Determine verdict (priority order)
    has_critical = any(d["delta"] < critical_threshold for d in regressions)
    has_overall_regression = overall_delta < overall_threshold
    has_improvement = overall_delta > promote_threshold

    if has_critical:
        verdict = Verdict.CRITICAL_REGRESSION
    elif has_overall_regression:
        verdict = Verdict.REGRESSION_DETECTED
    elif has_improvement:
        verdict = Verdict.IMPROVED
    else:
        verdict = Verdict.NO_SIGNIFICANT_CHANGE

    logger.info(
        "Verdict: %s (overall_delta=%.3f, regressions=%d, improvements=%d)",
        verdict,
        overall_delta,
        len(regressions),
        len(improvements),
    )

    return {
        "verdict": verdict,
        "regressions": regressions,
        "improvements": improvements,
    }


def generate_report(state: ComparatorState) -> dict[str, Any]:
    """
    Node 4: Produce a structured comparison report.
    """
    report: dict[str, Any] = {
        "verdict": state.get("verdict", "NO_SIGNIFICANT_CHANGE"),
        "v_new_id": state.get("v_new_id", ""),
        "v_current_id": state.get("v_current_id", ""),
        "v_new_score": state.get("v_new_quality_score", 0.0),
        "v_current_score": state.get("v_current_quality_score", 0.0),
        "delta": state.get("overall_delta", 0.0),
        "regressions": state.get("regressions", []),
        "improvements": state.get("improvements", []),
        "dimension_deltas": state.get("deltas", {}),
        "thresholds_used": {
            k: v
            for k, v in state.get("thresholds", {}).items()
            if k in (
                "overall_regression_threshold",
                "critical_dimension_threshold",
                "auto_promote_threshold",
            )
        },
    }

    logger.info(
        "Comparison report: verdict=%s, delta=%.3f (%s → %s)",
        report["verdict"],
        report["delta"],
        report["v_current_id"],
        report["v_new_id"],
    )

    return {"comparison_report": report}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_comparator_graph():
    """
    Build the Version Comparator LangGraph StateGraph.

    Returns a compiled graph: invoke with {v_new_id, v_current_id} or
    pre-loaded {v_new_scores, v_current_scores}.
    """
    from langgraph.graph import END, StateGraph

    graph = StateGraph(ComparatorState)

    graph.add_node("fetch_scores", fetch_scores)
    graph.add_node("compare_dimensions", compare_dimensions)
    graph.add_node("detect_regression", detect_regression)
    graph.add_node("generate_report", generate_report)

    graph.set_entry_point("fetch_scores")
    graph.add_edge("fetch_scores", "compare_dimensions")
    graph.add_edge("compare_dimensions", "detect_regression")
    graph.add_edge("detect_regression", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

# Module-level compiled graph — built once on first call.
_COMPARATOR_GRAPH: Any = None


def compare_versions(
    v_new_id: str = "",
    v_current_id: str = "",
    v_new_scores: dict[str, Any] | None = None,
    v_current_scores: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Compare two versions and return a comparison report.

    Can accept pre-loaded scores (from orchestrator state) or fetch them
    from MCP Storage using version IDs.

    Args:
        v_new_id: Version ID of the new version.
        v_current_id: Version ID of the current production version.
        v_new_scores: Pre-loaded eval results for v_new (optional).
        v_current_scores: Pre-loaded eval results for v_current (optional).

    Returns:
        Comparison report dict with verdict, delta, regressions, improvements.
    """
    global _COMPARATOR_GRAPH
    if _COMPARATOR_GRAPH is None:
        _COMPARATOR_GRAPH = build_comparator_graph()

    initial_state: ComparatorState = {
        "v_new_id": v_new_id,
        "v_current_id": v_current_id,
        "v_new_scores": v_new_scores or {},
        "v_current_scores": v_current_scores or {},
        "errors": [],
    }

    result = _COMPARATOR_GRAPH.invoke(initial_state)
    return result.get("comparison_report", {})
