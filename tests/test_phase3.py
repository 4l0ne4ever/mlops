"""
Phase 3 — Decision Layer Unit & Integration Tests.

Tests all Phase 3 components:
    - P3-1: Version Comparator Agent (state graph, verdicts, thresholds)
    - P3-2: Regression detection thresholds
    - P3-3: Promotion Decision Agent (state graph, decision matrix, actions)
    - P3-4: Notification system (escalate / rollback notifications)
    - P3-5: Orchestrator integration (new nodes, graph wiring)

Run:
    python tests/test_phase3.py

Expected: all tests pass without API keys or running servers.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Resolve project root
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "agents"))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "comparator"))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "decision"))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "orchestrator"))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "eval_runner"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "storage"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "deploy"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "monitor"))

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

_pass_count = 0
_fail_count = 0


def test(name: str, condition: bool, detail: str = "") -> None:
    global _pass_count, _fail_count
    if condition:
        _pass_count += 1
        print(f"  \u2705 {name}")
    else:
        _fail_count += 1
        msg = f"  \u274c {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


# ============================================================================
# HELPER: build score dicts for comparator tests
# ============================================================================

def _make_scores(
    quality_score: float,
    task_completion: float = 7.0,
    output_quality: float = 7.0,
    latency: float = 7.0,
    cost_efficiency: float = 7.0,
) -> dict:
    return {
        "quality_score": quality_score,
        "score_breakdown": {
            "task_completion": task_completion,
            "output_quality": output_quality,
            "latency": latency,
            "cost_efficiency": cost_efficiency,
        },
    }


# ============================================================================
# TEST SECTION 1: Comparator Agent — Imports & Module Structure
# ============================================================================

print("\n== SECTION 1: Comparator Agent — Module Structure ==")

try:
    from agents.comparator.agent import (
        ComparatorState,
        _load_thresholds,
        _DIMENSION_KEYS,
        _DEFAULT_THRESHOLDS,
        fetch_scores,
        compare_dimensions,
        detect_regression,
        generate_report,
        build_comparator_graph,
        compare_versions,
    )
    _comparator_imported = True
except ImportError as e:
    _comparator_imported = False
    print(f"  Import error: {e}")

test("Comparator module imports", _comparator_imported)

test(
    "ComparatorState is a TypedDict-like",
    _comparator_imported and hasattr(ComparatorState, "__annotations__"),
)

test(
    "_DIMENSION_KEYS has 4 dimensions",
    _comparator_imported and len(_DIMENSION_KEYS) == 4,
    f"got {len(_DIMENSION_KEYS) if _comparator_imported else 0}",
)

expected_dims = {"task_completion", "output_quality", "latency", "cost_efficiency"}
test(
    "_DIMENSION_KEYS contains expected dims",
    _comparator_imported and set(_DIMENSION_KEYS) == expected_dims,
)

test(
    "Default thresholds have 3 keys",
    _comparator_imported and len(_DEFAULT_THRESHOLDS) == 3,
)

for key in ("overall_regression_threshold", "critical_dimension_threshold", "auto_promote_threshold"):
    test(
        f"Default threshold: {key}",
        _comparator_imported and key in _DEFAULT_THRESHOLDS,
    )

# ============================================================================
# TEST SECTION 2: Comparator — _load_thresholds
# ============================================================================

print("\n== SECTION 2: Comparator — _load_thresholds ==")

# 2a. Load from real config
thresholds = _load_thresholds() if _comparator_imported else {}
test(
    "Load thresholds from configs/thresholds.json",
    "overall_regression_threshold" in thresholds,
)
test(
    "overall_regression_threshold = -0.5",
    thresholds.get("overall_regression_threshold") == -0.5,
    f"got {thresholds.get('overall_regression_threshold')}",
)
test(
    "critical_dimension_threshold = -1.0",
    thresholds.get("critical_dimension_threshold") == -1.0,
    f"got {thresholds.get('critical_dimension_threshold')}",
)
test(
    "auto_promote_threshold = 0.3",
    thresholds.get("auto_promote_threshold") == 0.3,
    f"got {thresholds.get('auto_promote_threshold')}",
)

# 2b. Load from non-existent path (falls back to defaults)
defaults = _load_thresholds("/tmp/nonexistent_thresholds.json") if _comparator_imported else {}
test(
    "Non-existent path falls back to defaults",
    defaults == _DEFAULT_THRESHOLDS if _comparator_imported else False,
)

# 2c. Load from invalid JSON
tmp_invalid = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
tmp_invalid.write("NOT VALID JSON{{{")
tmp_invalid.close()
try:
    bad = _load_thresholds(tmp_invalid.name) if _comparator_imported else {}
    test(
        "Invalid JSON falls back to defaults",
        bad == _DEFAULT_THRESHOLDS if _comparator_imported else False,
    )
finally:
    os.unlink(tmp_invalid.name)


# ============================================================================
# TEST SECTION 3: Comparator — Node Functions (unit tests)
# ============================================================================

print("\n== SECTION 3: Comparator — Node Functions ==")

# 3a. fetch_scores — with pre-loaded data
state_fs: ComparatorState = {
    "v_new_id": "v_new_001",
    "v_current_id": "v_current_001",
    "v_new_scores": _make_scores(8.0, 8.5, 8.0, 7.5, 8.0),
    "v_current_scores": _make_scores(7.0, 7.0, 7.0, 7.0, 7.0),
    "errors": [],
}
result_fs = fetch_scores(state_fs)
test(
    "fetch_scores returns v_new_quality_score",
    result_fs.get("v_new_quality_score") == 8.0,
    f"got {result_fs.get('v_new_quality_score')}",
)
test(
    "fetch_scores returns v_current_quality_score",
    result_fs.get("v_current_quality_score") == 7.0,
    f"got {result_fs.get('v_current_quality_score')}",
)
test(
    "fetch_scores populates thresholds",
    "overall_regression_threshold" in result_fs.get("thresholds", {}),
)
test(
    "fetch_scores v_new_breakdown has 4 dims",
    len(result_fs.get("v_new_breakdown", {})) == 4,
)

# 3b. compare_dimensions
state_cd = {
    **state_fs,
    **result_fs,
}
result_cd = compare_dimensions(state_cd)
test(
    "compare_dimensions returns deltas dict",
    isinstance(result_cd.get("deltas"), dict),
)
test(
    "compare_dimensions overall_delta = 1.0",
    result_cd.get("overall_delta") == 1.0,
    f"got {result_cd.get('overall_delta')}",
)
test(
    "task_completion delta = 1.5",
    result_cd.get("deltas", {}).get("task_completion") == 1.5,
    f"got {result_cd.get('deltas', {}).get('task_completion')}",
)

# 3c. detect_regression — IMPROVED case
state_dr = {**state_cd, **result_cd}
result_dr = detect_regression(state_dr)
test(
    "detect_regression — IMPROVED verdict",
    result_dr.get("verdict") == "IMPROVED",
    f"got {result_dr.get('verdict')}",
)
test(
    "detect_regression — improvements list not empty",
    len(result_dr.get("improvements", [])) > 0,
)
test(
    "detect_regression — regressions list empty",
    len(result_dr.get("regressions", [])) == 0,
)

# 3d. generate_report
state_gr = {**state_dr, **result_dr}
result_gr = generate_report(state_gr)
report = result_gr.get("comparison_report", {})
test(
    "generate_report returns comparison_report",
    isinstance(report, dict) and "verdict" in report,
)
test(
    "Report contains v_new_id",
    report.get("v_new_id") == "v_new_001",
)
test(
    "Report contains delta",
    report.get("delta") == 1.0,
    f"got {report.get('delta')}",
)
test(
    "Report has thresholds_used",
    "overall_regression_threshold" in report.get("thresholds_used", {}),
)


# ============================================================================
# TEST SECTION 4: Comparator — Verdict Scenarios
# ============================================================================

print("\n== SECTION 4: Comparator — Verdict Scenarios ==")


def _run_comparator(v_new_scores, v_current_scores, v_new_id="v2", v_current_id="v1"):
    """Convenience: run full comparator graph inline."""
    return compare_versions(
        v_new_id=v_new_id,
        v_current_id=v_current_id,
        v_new_scores=v_new_scores,
        v_current_scores=v_current_scores,
    )


# 4a. IMPROVED — v_new significantly better
report_improved = _run_comparator(
    _make_scores(8.5, 9.0, 8.5, 8.0, 8.5),
    _make_scores(7.0, 7.0, 7.0, 7.0, 7.0),
)
test(
    "Verdict: IMPROVED",
    report_improved.get("verdict") == "IMPROVED",
    f"got {report_improved.get('verdict')}",
)
test(
    "IMPROVED: delta > 0",
    report_improved.get("delta", 0) > 0,
)

# 4b. NO_SIGNIFICANT_CHANGE — small delta
report_nochange = _run_comparator(
    _make_scores(7.1, 7.1, 7.1, 7.1, 7.1),
    _make_scores(7.0, 7.0, 7.0, 7.0, 7.0),
)
test(
    "Verdict: NO_SIGNIFICANT_CHANGE",
    report_nochange.get("verdict") == "NO_SIGNIFICANT_CHANGE",
    f"got {report_nochange.get('verdict')}",
)
test(
    "NO_SIGNIFICANT_CHANGE: delta small",
    abs(report_nochange.get("delta", 99)) < 0.5,
)

# 4c. REGRESSION_DETECTED — v_new is worse overall
report_regression = _run_comparator(
    _make_scores(6.0, 6.5, 6.0, 6.0, 6.0),
    _make_scores(7.0, 7.0, 7.0, 7.0, 7.0),
)
test(
    "Verdict: REGRESSION_DETECTED",
    report_regression.get("verdict") == "REGRESSION_DETECTED",
    f"got {report_regression.get('verdict')}",
)
test(
    "REGRESSION_DETECTED: delta < -0.5",
    report_regression.get("delta", 0) < -0.5,
)
test(
    "REGRESSION_DETECTED: has regressions",
    len(report_regression.get("regressions", [])) > 0,
)

# 4d. CRITICAL_REGRESSION — single dimension drops > 1.0
report_critical = _run_comparator(
    _make_scores(6.0, 7.0, 7.0, 5.5, 7.0),
    _make_scores(7.0, 7.0, 7.0, 7.0, 7.0),
)
test(
    "Verdict: CRITICAL_REGRESSION",
    report_critical.get("verdict") == "CRITICAL_REGRESSION",
    f"got {report_critical.get('verdict')}",
)
test(
    "CRITICAL_REGRESSION: has regressions",
    len(report_critical.get("regressions", [])) > 0,
)

# 4e. CRITICAL_REGRESSION takes priority over REGRESSION_DETECTED
report_priority = _run_comparator(
    _make_scores(5.5, 7.0, 5.8, 5.5, 7.0),  # overall drop AND critical dimension
    _make_scores(7.0, 7.0, 7.0, 7.0, 7.0),
)
test(
    "CRITICAL_REGRESSION priority over REGRESSION_DETECTED",
    report_priority.get("verdict") == "CRITICAL_REGRESSION",
    f"got {report_priority.get('verdict')}",
)


# ============================================================================
# TEST SECTION 5: Comparator — Graph Structure
# ============================================================================

print("\n== SECTION 5: Comparator — Graph Structure ==")

comp_graph = build_comparator_graph()
comp_graph_data = comp_graph.get_graph()
comp_node_names = sorted(comp_graph_data.nodes.keys())
# Filter out __start__ and __end__
comp_real_nodes = [n for n in comp_node_names if not n.startswith("__")]

test(
    "Comparator graph has 4 nodes",
    len(comp_real_nodes) == 4,
    f"got {len(comp_real_nodes)}: {comp_real_nodes}",
)

expected_comp_nodes = {"fetch_scores", "compare_dimensions", "detect_regression", "generate_report"}
test(
    "Comparator nodes are correct",
    set(comp_real_nodes) == expected_comp_nodes,
    f"got {set(comp_real_nodes)}",
)

# Check edges — entry point goes to fetch_scores
comp_edges = [(e.source, e.target) for e in comp_graph_data.edges]
test(
    "Entry point → fetch_scores",
    ("__start__", "fetch_scores") in comp_edges,
    f"edges: {comp_edges}",
)
test(
    "fetch_scores → compare_dimensions",
    ("fetch_scores", "compare_dimensions") in comp_edges,
)
test(
    "compare_dimensions → detect_regression",
    ("compare_dimensions", "detect_regression") in comp_edges,
)
test(
    "detect_regression → generate_report",
    ("detect_regression", "generate_report") in comp_edges,
)
test(
    "generate_report → __end__",
    ("generate_report", "__end__") in comp_edges,
)


# ============================================================================
# TEST SECTION 6: Decision Agent — Module Structure
# ============================================================================

print("\n== SECTION 6: Decision Agent — Module Structure ==")

try:
    from agents.decision.agent import (
        DecisionState,
        DECISION_AUTO_PROMOTE,
        DECISION_NO_ACTION,
        DECISION_ESCALATE,
        DECISION_ROLLBACK,
        _VERDICT_TO_DECISION,
        receive_report,
        apply_rules,
        execute_action,
        log_decision,
        _send_notification,
        build_decision_graph,
        make_decision,
    )
    _decision_imported = True
except ImportError as e:
    _decision_imported = False
    print(f"  Import error: {e}")

test("Decision module imports", _decision_imported)

test(
    "DecisionState is a TypedDict-like",
    _decision_imported and hasattr(DecisionState, "__annotations__"),
)

# Constants
test("DECISION_AUTO_PROMOTE = 'AUTO_PROMOTE'", DECISION_AUTO_PROMOTE == "AUTO_PROMOTE")
test("DECISION_NO_ACTION = 'NO_ACTION'", DECISION_NO_ACTION == "NO_ACTION")
test("DECISION_ESCALATE = 'ESCALATE'", DECISION_ESCALATE == "ESCALATE")
test("DECISION_ROLLBACK = 'ROLLBACK'", DECISION_ROLLBACK == "ROLLBACK")

# Decision map
test(
    "Verdict map: IMPROVED → AUTO_PROMOTE",
    _VERDICT_TO_DECISION.get("IMPROVED") == "AUTO_PROMOTE",
)
test(
    "Verdict map: NO_SIGNIFICANT_CHANGE → NO_ACTION",
    _VERDICT_TO_DECISION.get("NO_SIGNIFICANT_CHANGE") == "NO_ACTION",
)
test(
    "Verdict map: REGRESSION_DETECTED → ESCALATE",
    _VERDICT_TO_DECISION.get("REGRESSION_DETECTED") == "ESCALATE",
)
test(
    "Verdict map: CRITICAL_REGRESSION → ROLLBACK",
    _VERDICT_TO_DECISION.get("CRITICAL_REGRESSION") == "ROLLBACK",
)


# ============================================================================
# TEST SECTION 7: Decision Agent — Node Functions
# ============================================================================

print("\n== SECTION 7: Decision Agent — Node Functions ==")

# Create temp data dir for decision tests
_decision_tmp = tempfile.mkdtemp(prefix="decision_test_")

# 7a. receive_report
report_input = {
    "verdict": "IMPROVED",
    "v_new_id": "v_new_002",
    "v_current_id": "v_current_002",
    "delta": 1.5,
    "regressions": [],
    "improvements": [{"dimension": "task_completion", "old": 7.0, "new": 8.5, "delta": 1.5}],
    "dimension_deltas": {"task_completion": 1.5, "output_quality": 1.0, "latency": 0.5, "cost_efficiency": 0.5},
    "thresholds_used": {"overall_regression_threshold": -0.5, "critical_dimension_threshold": -1.0, "auto_promote_threshold": 0.3},
}
rr_state: DecisionState = {"comparison_report": report_input, "errors": []}
rr_result = receive_report(rr_state)
test(
    "receive_report extracts v_new_id",
    rr_result.get("v_new_id") == "v_new_002",
)
test(
    "receive_report extracts v_current_id",
    rr_result.get("v_current_id") == "v_current_002",
)
test(
    "receive_report no errors for valid report",
    len(rr_result.get("errors", [])) == 0,
)

# 7b. receive_report — missing verdict
rr_bad_state: DecisionState = {"comparison_report": {}, "errors": []}
rr_bad = receive_report(rr_bad_state)
test(
    "receive_report error when no verdict",
    any("No verdict" in e for e in rr_bad.get("errors", [])),
)

# 7c. apply_rules — IMPROVED → AUTO_PROMOTE
ar_state: DecisionState = {
    "comparison_report": report_input,
    "errors": [],
}
ar_result = apply_rules(ar_state)
test(
    "apply_rules: IMPROVED → AUTO_PROMOTE",
    ar_result.get("decision") == "AUTO_PROMOTE",
    f"got {ar_result.get('decision')}",
)
test(
    "apply_rules: reasoning mentions improved",
    "improved" in ar_result.get("reasoning", "").lower()
    or "auto-promote" in ar_result.get("reasoning", "").lower(),
)
test(
    "apply_rules: confidence = high for IMPROVED",
    ar_result.get("confidence") == "high",
)

# 7d. apply_rules — NO_SIGNIFICANT_CHANGE → NO_ACTION
nochange_report = {**report_input, "verdict": "NO_SIGNIFICANT_CHANGE", "delta": 0.1}
ar_nochange = apply_rules({"comparison_report": nochange_report, "errors": []})
test(
    "apply_rules: NO_SIGNIFICANT_CHANGE → NO_ACTION",
    ar_nochange.get("decision") == "NO_ACTION",
)
test(
    "apply_rules: confidence = medium for NO_ACTION",
    ar_nochange.get("confidence") == "medium",
)

# 7e. apply_rules — REGRESSION_DETECTED → ESCALATE
reg_report = {
    **report_input,
    "verdict": "REGRESSION_DETECTED",
    "delta": -0.7,
    "regressions": [{"dimension": "output_quality", "old": 7.0, "new": 6.3, "delta": -0.7}],
    "improvements": [],
}
ar_escalate = apply_rules({"comparison_report": reg_report, "errors": []})
test(
    "apply_rules: REGRESSION_DETECTED → ESCALATE",
    ar_escalate.get("decision") == "ESCALATE",
    f"got {ar_escalate.get('decision')}",
)
test(
    "apply_rules: reasoning mentions escalat",
    "escalat" in ar_escalate.get("reasoning", "").lower(),
)

# 7f. apply_rules — CRITICAL_REGRESSION → ROLLBACK
crit_report = {
    **report_input,
    "verdict": "CRITICAL_REGRESSION",
    "delta": -1.5,
    "regressions": [{"dimension": "latency", "old": 7.0, "new": 5.5, "delta": -1.5}],
    "improvements": [],
}
ar_rollback = apply_rules({"comparison_report": crit_report, "errors": []})
test(
    "apply_rules: CRITICAL_REGRESSION → ROLLBACK",
    ar_rollback.get("decision") == "ROLLBACK",
    f"got {ar_rollback.get('decision')}",
)
test(
    "apply_rules: confidence = high for ROLLBACK",
    ar_rollback.get("confidence") == "high",
)
test(
    "apply_rules: reasoning mentions rollback or rolling",
    "rollback" in ar_rollback.get("reasoning", "").lower()
    or "rolling" in ar_rollback.get("reasoning", "").lower(),
)


# ============================================================================
# TEST SECTION 8: Decision Agent — execute_action
# ============================================================================

print("\n== SECTION 8: Decision Agent — execute_action ==")

# 8a. NO_ACTION
ea_noaction_state: DecisionState = {
    "decision": "NO_ACTION",
    "v_new_id": "v_new_003",
    "v_current_id": "v_current_003",
    "errors": [],
}
ea_noaction = execute_action(ea_noaction_state)
test(
    "execute_action NO_ACTION: no_action in result",
    ea_noaction.get("action_result", {}).get("no_action") is True,
)
test(
    "execute_action NO_ACTION: action_taken describes no action",
    "no action" in ea_noaction.get("action_taken", "").lower(),
)

# 8b. ESCALATE
ea_escalate_state: DecisionState = {
    "decision": "ESCALATE",
    "v_new_id": "v_esc_001",
    "v_current_id": "v_cur_001",
    "errors": [],
}
ea_escalate = execute_action(ea_escalate_state)
test(
    "execute_action ESCALATE: escalated in result",
    ea_escalate.get("action_result", {}).get("escalated") is True,
)
test(
    "execute_action ESCALATE: action_taken mentions escalate",
    "escalat" in ea_escalate.get("action_taken", "").lower(),
)

# 8c. AUTO_PROMOTE — deploy v_new (using temp dir)
with patch.dict(os.environ, {
    "APP_CONFIG": str(PROJECT_ROOT / "configs" / "local.json"),
    "DEPLOY_DATA_DIR": _decision_tmp,
    "STORAGE_DATA_DIR": _decision_tmp,
}):
    ea_promote_state: DecisionState = {
        "decision": "AUTO_PROMOTE",
        "v_new_id": f"v_promote_{uuid.uuid4().hex[:8]}",
        "v_current_id": "v_cur_old",
        "errors": [],
    }
    ea_promote = execute_action(ea_promote_state)
    test(
        "execute_action AUTO_PROMOTE: has deployment_id",
        "deployment_id" in str(ea_promote.get("action_result", {})),
    )
    test(
        "execute_action AUTO_PROMOTE: action_taken mentions deployed",
        "deployed" in ea_promote.get("action_taken", "").lower()
        or "deploy" in ea_promote.get("action_taken", "").lower(),
    )

# 8d. ROLLBACK — rollback to v_current
with patch.dict(os.environ, {
    "APP_CONFIG": str(PROJECT_ROOT / "configs" / "local.json"),
    "DEPLOY_DATA_DIR": _decision_tmp,
}):
    ea_rollback_state: DecisionState = {
        "decision": "ROLLBACK",
        "v_new_id": "v_bad",
        "v_current_id": f"v_rollback_{uuid.uuid4().hex[:8]}",
        "errors": [],
    }
    ea_rollback = execute_action(ea_rollback_state)
    test(
        "execute_action ROLLBACK: has deployment_id",
        "deployment_id" in str(ea_rollback.get("action_result", {})),
    )
    test(
        "execute_action ROLLBACK: action_taken mentions rollback",
        "rolled back" in ea_rollback.get("action_taken", "").lower()
        or "rollback" in ea_rollback.get("action_taken", "").lower(),
    )


# ============================================================================
# TEST SECTION 9: Decision Agent — log_decision & Notifications
# ============================================================================

print("\n== SECTION 9: Decision Agent — log_decision & Notifications ==")

with patch.dict(os.environ, {
    "STORAGE_DATA_DIR": _decision_tmp,
    "MONITOR_DATA_DIR": _decision_tmp,
}):
    # 9a. log_decision for AUTO_PROMOTE (no notification)
    ld_promote_state: DecisionState = {
        "decision": "AUTO_PROMOTE",
        "reasoning": "Quality improved significantly.",
        "confidence": "high",
        "run_id": f"run_promote_{uuid.uuid4().hex[:8]}",
        "v_new_id": "v_new_100",
        "v_current_id": "v_cur_100",
        "action_taken": "Deployed v_new_100",
        "action_result": {"deployment_id": "dep-001"},
        "comparison_report": report_input,
        "errors": [],
    }
    ld_promote = log_decision(ld_promote_state)
    test(
        "log_decision AUTO_PROMOTE: logged",
        ld_promote.get("decision_logged") is True,
    )
    test(
        "log_decision AUTO_PROMOTE: no notification",
        ld_promote.get("notification_sent") is False,
    )

    # Verify decision file saved
    decision_file = Path(_decision_tmp) / "decisions" / f"{ld_promote_state['run_id']}.json"
    test(
        "log_decision: decision JSON file created",
        decision_file.exists(),
    )
    if decision_file.exists():
        decision_data = json.loads(decision_file.read_text(encoding="utf-8"))
        test(
            "log_decision: file contains decision",
            decision_data.get("decision") == "AUTO_PROMOTE",
        )
        test(
            "log_decision: file contains reasoning",
            "improved" in decision_data.get("reasoning", "").lower(),
        )
        test(
            "log_decision: file contains timestamp",
            "timestamp" in decision_data,
        )

    # 9b. log_decision for ESCALATE (notification sent)
    ld_escalate_state: DecisionState = {
        "decision": "ESCALATE",
        "reasoning": "Score dropped below threshold.",
        "confidence": "medium",
        "run_id": f"run_esc_{uuid.uuid4().hex[:8]}",
        "v_new_id": "v_esc_200",
        "v_current_id": "v_cur_200",
        "action_taken": "Escalated for review",
        "action_result": {"escalated": True},
        "comparison_report": reg_report,
        "errors": [],
    }
    ld_escalate = log_decision(ld_escalate_state)
    test(
        "log_decision ESCALATE: notification sent",
        ld_escalate.get("notification_sent") is True,
    )

    # Verify notification file (filename now has a timestamp suffix)
    _notif_dir = Path(_decision_tmp) / "notifications"
    notif_files_esc = list(_notif_dir.glob(f"{ld_escalate_state['run_id']}_*.json"))
    test(
        "Notification file created for ESCALATE",
        len(notif_files_esc) > 0,
    )
    if notif_files_esc:
        notif_data = json.loads(notif_files_esc[0].read_text(encoding="utf-8"))
        test(
            "Notification severity = WARNING for ESCALATE",
            notif_data.get("severity") == "WARNING",
        )
        test(
            "Notification has subject",
            len(notif_data.get("subject", "")) > 0,
        )
        test(
            "Notification has body",
            len(notif_data.get("body", "")) > 0,
        )
        test(
            "Notification channel = log",
            notif_data.get("channel") == "log",
        )

    # 9c. log_decision for ROLLBACK (notification sent)
    ld_rollback_state: DecisionState = {
        "decision": "ROLLBACK",
        "reasoning": "Critical regression detected.",
        "confidence": "high",
        "run_id": f"run_rb_{uuid.uuid4().hex[:8]}",
        "v_new_id": "v_rb_300",
        "v_current_id": "v_cur_300",
        "action_taken": "Rolled back to v_cur_300",
        "action_result": {"deployment_id": "dep-rb-001"},
        "comparison_report": crit_report,
        "errors": [],
    }
    ld_rollback = log_decision(ld_rollback_state)
    test(
        "log_decision ROLLBACK: notification sent",
        ld_rollback.get("notification_sent") is True,
    )

    notif_rb_files = list((Path(_decision_tmp) / "notifications").glob(
        f"{ld_rollback_state['run_id']}_*.json"
    ))
    if notif_rb_files:
        notif_rb_data = json.loads(notif_rb_files[0].read_text(encoding="utf-8"))
        test(
            "Notification severity = CRITICAL for ROLLBACK",
            notif_rb_data.get("severity") == "CRITICAL",
        )

    # 9d. log_decision for NO_ACTION (no notification)
    ld_noaction_state: DecisionState = {
        "decision": "NO_ACTION",
        "reasoning": "No significant change.",
        "confidence": "medium",
        "run_id": f"run_na_{uuid.uuid4().hex[:8]}",
        "v_new_id": "v_na_400",
        "v_current_id": "v_cur_400",
        "action_taken": "No action taken",
        "action_result": {"no_action": True},
        "comparison_report": nochange_report,
        "errors": [],
    }
    ld_noaction = log_decision(ld_noaction_state)
    test(
        "log_decision NO_ACTION: no notification",
        ld_noaction.get("notification_sent") is False,
    )


# ============================================================================
# TEST SECTION 10: Decision Agent — Graph Structure
# ============================================================================

print("\n== SECTION 10: Decision Agent — Graph Structure ==")

dec_graph = build_decision_graph()
dec_graph_data = dec_graph.get_graph()
dec_node_names = sorted(dec_graph_data.nodes.keys())
dec_real_nodes = [n for n in dec_node_names if not n.startswith("__")]

test(
    "Decision graph has 4 nodes",
    len(dec_real_nodes) == 4,
    f"got {len(dec_real_nodes)}: {dec_real_nodes}",
)

expected_dec_nodes = {"receive_report", "apply_rules", "execute_action", "log_decision"}
test(
    "Decision nodes are correct",
    set(dec_real_nodes) == expected_dec_nodes,
    f"got {set(dec_real_nodes)}",
)

dec_edges = [(e.source, e.target) for e in dec_graph_data.edges]
test("Entry → receive_report", ("__start__", "receive_report") in dec_edges)
test("receive_report → apply_rules", ("receive_report", "apply_rules") in dec_edges)
test("apply_rules → execute_action", ("apply_rules", "execute_action") in dec_edges)
test("execute_action → log_decision", ("execute_action", "log_decision") in dec_edges)
test("log_decision → __end__", ("log_decision", "__end__") in dec_edges)


# ============================================================================
# TEST SECTION 11: Decision Agent — Full Pipeline (make_decision)
# ============================================================================

print("\n== SECTION 11: Decision Agent — Full Pipeline ==")

with patch.dict(os.environ, {
    "STORAGE_DATA_DIR": _decision_tmp,
    "MONITOR_DATA_DIR": _decision_tmp,
    "DEPLOY_DATA_DIR": _decision_tmp,
    "APP_CONFIG": str(PROJECT_ROOT / "configs" / "local.json"),
}):
    # 11a. Full pipeline — IMPROVED → AUTO_PROMOTE
    md_promote = make_decision(report_input, run_id=f"full_promote_{uuid.uuid4().hex[:8]}")
    test(
        "make_decision IMPROVED: decision=AUTO_PROMOTE",
        md_promote.get("decision") == "AUTO_PROMOTE",
        f"got {md_promote.get('decision')}",
    )
    test(
        "make_decision IMPROVED: decision_logged",
        md_promote.get("decision_logged") is True,
    )
    test(
        "make_decision IMPROVED: no notification",
        md_promote.get("notification_sent") is False,
    )

    # 11b. Full pipeline — CRITICAL_REGRESSION → ROLLBACK
    md_rollback = make_decision(crit_report, run_id=f"full_rb_{uuid.uuid4().hex[:8]}")
    test(
        "make_decision CRITICAL: decision=ROLLBACK",
        md_rollback.get("decision") == "ROLLBACK",
        f"got {md_rollback.get('decision')}",
    )
    test(
        "make_decision CRITICAL: notification sent",
        md_rollback.get("notification_sent") is True,
    )

    # 11c. Full pipeline — REGRESSION_DETECTED → ESCALATE
    md_escalate = make_decision(reg_report, run_id=f"full_esc_{uuid.uuid4().hex[:8]}")
    test(
        "make_decision REGRESSION: decision=ESCALATE",
        md_escalate.get("decision") == "ESCALATE",
        f"got {md_escalate.get('decision')}",
    )

    # 11d. Full pipeline — NO_SIGNIFICANT_CHANGE → NO_ACTION
    md_noaction = make_decision(nochange_report, run_id=f"full_na_{uuid.uuid4().hex[:8]}")
    test(
        "make_decision NO_CHANGE: decision=NO_ACTION",
        md_noaction.get("decision") == "NO_ACTION",
        f"got {md_noaction.get('decision')}",
    )


# ============================================================================
# TEST SECTION 12: Orchestrator — Phase 3 Integration (Graph Updates)
# ============================================================================

print("\n== SECTION 12: Orchestrator — Phase 3 Graph Integration ==")

try:
    from agents.orchestrator.agent import (
        OrchestratorState,
        build_orchestrator_graph,
        compare_versions_node,
        make_decision_node,
        route_result as orch_route_result,
    )
    _orch_imported = True
except ImportError as e:
    _orch_imported = False
    print(f"  Import error: {e}")

test("Orchestrator imports Phase 3 nodes", _orch_imported)

# 12a. OrchestratorState has new fields
orch_annotations = OrchestratorState.__annotations__ if _orch_imported else {}
test(
    "OrchestratorState has comparison_report field",
    "comparison_report" in orch_annotations,
)
test(
    "OrchestratorState has decision field",
    "decision" in orch_annotations,
)

# 12b. Graph structure — 8 real nodes
orch_graph = build_orchestrator_graph() if _orch_imported else None
if orch_graph:
    orch_gdata = orch_graph.get_graph()
    orch_nodes = sorted(orch_gdata.nodes.keys())
    orch_real_nodes = [n for n in orch_nodes if not n.startswith("__")]

    test(
        "Orchestrator graph has 8 nodes",
        len(orch_real_nodes) == 8,
        f"got {len(orch_real_nodes)}: {orch_real_nodes}",
    )

    expected_orch_nodes = {
        "receive_trigger", "parse_change", "check_lock",
        "prepare_eval", "run_eval",
        "compare_versions", "make_decision",
        "route_result",
    }
    test(
        "Orchestrator has all Phase 3 nodes",
        set(orch_real_nodes) == expected_orch_nodes,
        f"got {set(orch_real_nodes)}",
    )

    # Check edges
    orch_edges = [(e.source, e.target) for e in orch_gdata.edges]

    test(
        "Edge: __start__ → receive_trigger",
        ("__start__", "receive_trigger") in orch_edges,
    )
    test(
        "Edge: receive_trigger → parse_change",
        ("receive_trigger", "parse_change") in orch_edges,
    )
    test(
        "Edge: parse_change → check_lock",
        ("parse_change", "check_lock") in orch_edges,
    )
    test(
        "Edge: prepare_eval → run_eval",
        ("prepare_eval", "run_eval") in orch_edges,
    )

    # New Phase 3 edges
    test(
        "Edge: run_eval → compare_versions (conditional)",
        ("run_eval", "compare_versions") in orch_edges,
    )
    test(
        "Edge: compare_versions → make_decision",
        ("compare_versions", "make_decision") in orch_edges,
    )
    test(
        "Edge: make_decision → route_result",
        ("make_decision", "route_result") in orch_edges,
    )
    test(
        "Edge: route_result → __end__",
        ("route_result", "__end__") in orch_edges,
    )

    # Conditional edges
    test(
        "Edge: check_lock → route_result (conditional skip)",
        ("check_lock", "route_result") in orch_edges,
    )
    test(
        "Edge: check_lock → prepare_eval (conditional proceed)",
        ("check_lock", "prepare_eval") in orch_edges,
    )
    test(
        "Edge: run_eval → route_result (conditional error skip)",
        ("run_eval", "route_result") in orch_edges,
    )
else:
    for i in range(13):
        test("Orchestrator graph test (skipped — import failed)", False)


# ============================================================================
# TEST SECTION 13: Orchestrator — compare_versions_node (unit)
# ============================================================================

print("\n== SECTION 13: Orchestrator — compare_versions_node ==")

# Mock a state with eval results already populated
with patch.dict(os.environ, {"STORAGE_DATA_DIR": _decision_tmp}):
    cvn_state = {
        "run_id": "cvn_test_001",
        "version_id": "v_new_cvn",
        "eval_result": {
            "version_id": "v_new_cvn",
            "quality_score": 8.0,
            "score_breakdown": {
                "task_completion": 8.5,
                "output_quality": 8.0,
                "latency": 7.5,
                "cost_efficiency": 8.0,
            },
        },
        "quality_score": 8.0,
        "errors": [],
    }
    cvn_result = compare_versions_node(cvn_state) if _orch_imported else {}
    test(
        "compare_versions_node returns comparison_report",
        isinstance(cvn_result.get("comparison_report"), dict),
    )
    report_cvn = cvn_result.get("comparison_report", {})
    test(
        "compare_versions_node: report has verdict",
        "verdict" in report_cvn,
    )
    # Without promoted version, current scores = 0, so v_new is a big improvement
    test(
        "compare_versions_node: first deploy = IMPROVED",
        report_cvn.get("verdict") == "IMPROVED",
        f"got {report_cvn.get('verdict')}",
    )


# ============================================================================
# TEST SECTION 14: Orchestrator — make_decision_node (unit)
# ============================================================================

print("\n== SECTION 14: Orchestrator — make_decision_node ==")

with patch.dict(os.environ, {
    "STORAGE_DATA_DIR": _decision_tmp,
    "MONITOR_DATA_DIR": _decision_tmp,
    "DEPLOY_DATA_DIR": _decision_tmp,
    "APP_CONFIG": str(PROJECT_ROOT / "configs" / "local.json"),
}):
    mdn_state = {
        "run_id": f"mdn_test_{uuid.uuid4().hex[:8]}",
        "comparison_report": report_improved,
        "errors": [],
    }
    mdn_result = make_decision_node(mdn_state) if _orch_imported else {}
    test(
        "make_decision_node returns decision dict",
        isinstance(mdn_result.get("decision"), dict),
    )
    test(
        "make_decision_node: decision=AUTO_PROMOTE for IMPROVED",
        mdn_result.get("decision", {}).get("decision") == "AUTO_PROMOTE",
        f"got {mdn_result.get('decision', {}).get('decision')}",
    )

    # No comparison report → NO_ACTION
    mdn_empty_state = {
        "run_id": "mdn_empty",
        "comparison_report": {},
        "errors": [],
    }
    mdn_empty = make_decision_node(mdn_empty_state) if _orch_imported else {}
    test(
        "make_decision_node: empty report → NO_ACTION",
        mdn_empty.get("decision", {}).get("decision") == "NO_ACTION",
    )


# ============================================================================
# TEST SECTION 15: Orchestrator — route_result saves Phase 3 data
# ============================================================================

print("\n== SECTION 15: Orchestrator — route_result with Phase 3 data ==")

with patch.dict(os.environ, {"STORAGE_DATA_DIR": _decision_tmp}):
    rr_run_id = f"route_p3_{uuid.uuid4().hex[:8]}"
    rr_state: OrchestratorState = {
        "run_id": rr_run_id,
        "trigger_type": "manual",
        "change_type": "prompt_update",
        "changed_files": ["configs/prompt_template.json"],
        "commit_sha": "abc123",
        "branch": "main",
        "version_id": "v_rr_test",
        "quality_score": 8.5,
        "comparison_report": report_improved,
        "decision": {"decision": "AUTO_PROMOTE", "reasoning": "Quality improved"},
        "status": "completed",
        "started_at": "2024-01-01T00:00:00Z",
        "lock_acquired": False,
        "errors": [],
    }
    rr_out = orch_route_result(rr_state) if _orch_imported else {}
    test(
        "route_result returns status=completed",
        rr_out.get("status") == "completed",
    )

    # Check saved JSON includes comparison_report and decision
    rr_saved_path = Path(_decision_tmp) / "pipeline-runs" / f"{rr_run_id}.json"
    if rr_saved_path.exists():
        rr_saved = json.loads(rr_saved_path.read_text(encoding="utf-8"))
        test(
            "Saved run: has comparison_report",
            isinstance(rr_saved.get("comparison_report"), dict),
        )
        test(
            "Saved run: comparison_report has verdict",
            "verdict" in rr_saved.get("comparison_report", {}),
        )
        test(
            "Saved run: has decision",
            isinstance(rr_saved.get("decision"), dict),
        )
        test(
            "Saved run: decision has decision key",
            "decision" in rr_saved.get("decision", {}),
        )
    else:
        test("Saved run: file exists", False, f"path: {rr_saved_path}")
        for _ in range(3):
            test("Saved run: (skipped)", False)


# ============================================================================
# TEST SECTION 16: Edge Cases & Boundary Conditions
# ============================================================================

print("\n== SECTION 16: Edge Cases & Boundary Conditions ==")

# 16a. Exact boundary — delta = exactly threshold values
# exactly -0.5 → REGRESSION (delta < threshold means strictly less)
report_exact_regression = _run_comparator(
    _make_scores(6.5, 7.0, 7.0, 7.0, 7.0),
    _make_scores(7.0, 7.0, 7.0, 7.0, 7.0),
)
# overall_delta = -0.5, threshold = -0.5, "< -0.5" is False so should be NO_SIGNIFICANT_CHANGE
test(
    "Boundary: delta=-0.5 exactly → NOT regression",
    report_exact_regression.get("verdict") != "REGRESSION_DETECTED",
    f"got {report_exact_regression.get('verdict')} (delta={report_exact_regression.get('delta')})",
)

# exactly +0.3 → NOT improved (> threshold, not >=)
report_exact_promote = _run_comparator(
    _make_scores(7.3, 7.0, 7.0, 7.0, 7.0),
    _make_scores(7.0, 7.0, 7.0, 7.0, 7.0),
)
test(
    "Boundary: delta=+0.3 exactly → NOT improved",
    report_exact_promote.get("verdict") != "IMPROVED",
    f"got {report_exact_promote.get('verdict')} (delta={report_exact_promote.get('delta')})",
)

# 16b. Zero scores — both versions have 0
report_zero = _run_comparator(
    _make_scores(0.0, 0.0, 0.0, 0.0, 0.0),
    _make_scores(0.0, 0.0, 0.0, 0.0, 0.0),
)
test(
    "Zero scores → NO_SIGNIFICANT_CHANGE",
    report_zero.get("verdict") == "NO_SIGNIFICANT_CHANGE",
    f"got {report_zero.get('verdict')}",
)

# 16c. compare_versions with empty scores
report_empty = _run_comparator({}, {}, "v_empty_new", "v_empty_cur")
test(
    "Empty scores don't crash",
    isinstance(report_empty, dict),
)
test(
    "Empty scores produce a verdict",
    "verdict" in report_empty,
)

# 16d. Unknown verdict in decision agent
unknown_report = {**report_input, "verdict": "SOMETHING_WEIRD"}
ar_unknown = apply_rules({"comparison_report": unknown_report, "errors": []})
test(
    "Unknown verdict → NO_ACTION",
    ar_unknown.get("decision") == "NO_ACTION",
)


# ============================================================================
# TEST SECTION 17: Dict Breakdown Handling (Fix P1-1)
# ============================================================================
#
# QualityScoreCalculator.to_dict() emits:
#   {dim: {"score": float, "weight": float, "raw_value": float}}
# rather than the flat {dim: float} shape that the original comparator
# assumed.  The fix in compare_dimensions and detect_regression must
# extract the "score" sub-key transparently.
#
print("\n== SECTION 17: Dict Breakdown Handling (Fix P1-1) ==")


def _make_dict_breakdown_scores(
    quality_score: float,
    task_completion: float = 7.0,
    output_quality: float = 7.0,
    latency: float = 7.0,
    cost_efficiency: float = 7.0,
) -> dict:
    """Return v_*_scores using the QualityScoreCalculator nested-dict shape."""
    return {
        "quality_score": quality_score,
        "score_breakdown": {
            "task_completion": {"score": task_completion, "weight": 0.35, "raw_value": task_completion},
            "output_quality": {"score": output_quality, "weight": 0.35, "raw_value": output_quality},
            "latency": {"score": latency, "weight": 0.15, "raw_value": latency},
            "cost_efficiency": {"score": cost_efficiency, "weight": 0.15, "raw_value": cost_efficiency},
        },
    }


# 17a. IMPROVED using dict breakdowns
report_dict_improved = _run_comparator(
    _make_dict_breakdown_scores(8.5, 9.0, 8.5, 8.0, 8.5),
    _make_dict_breakdown_scores(7.0, 7.0, 7.0, 7.0, 7.0),
)
test(
    "Dict breakdown: does not crash",
    isinstance(report_dict_improved, dict),
)
test(
    "Dict breakdown IMPROVED: verdict = IMPROVED",
    report_dict_improved.get("verdict") == "IMPROVED",
    f"got {report_dict_improved.get('verdict')}",
)
test(
    "Dict breakdown IMPROVED: delta = 1.5",
    report_dict_improved.get("delta") == 1.5,
    f"got {report_dict_improved.get('delta')}",
)
test(
    "Dict breakdown IMPROVED: improvements populated",
    len(report_dict_improved.get("improvements", [])) > 0,
)

# 17b. REGRESSION using dict breakdowns
report_dict_reg = _run_comparator(
    _make_dict_breakdown_scores(6.0, 6.5, 6.0, 6.0, 6.0),
    _make_dict_breakdown_scores(7.0, 7.0, 7.0, 7.0, 7.0),
)
test(
    "Dict breakdown REGRESSION: verdict = REGRESSION_DETECTED",
    report_dict_reg.get("verdict") == "REGRESSION_DETECTED",
    f"got {report_dict_reg.get('verdict')}",
)
test(
    "Dict breakdown REGRESSION: regressions list populated",
    len(report_dict_reg.get("regressions", [])) > 0,
)

# 17c. Regression entries must carry float values (not dicts) in old/new fields
regs_dict = report_dict_reg.get("regressions", [])
if regs_dict:
    test(
        "Dict breakdown: regression entry 'old' is float",
        isinstance(regs_dict[0].get("old"), float),
        f"type={type(regs_dict[0].get('old')).__name__}, value={regs_dict[0].get('old')}",
    )
    test(
        "Dict breakdown: regression entry 'new' is float",
        isinstance(regs_dict[0].get("new"), float),
        f"type={type(regs_dict[0].get('new')).__name__}, value={regs_dict[0].get('new')}",
    )
else:
    test("Dict breakdown regression entry check (skipped)", False, "no regressions found")
    test("Dict breakdown regression entry check (skipped)", False, "no regressions found")

# 17d. CRITICAL_REGRESSION using dict breakdowns
report_dict_crit = _run_comparator(
    _make_dict_breakdown_scores(6.0, 7.0, 7.0, 5.5, 7.0),  # latency drop > 1.0
    _make_dict_breakdown_scores(7.0, 7.0, 7.0, 7.0, 7.0),
)
test(
    "Dict breakdown CRITICAL: verdict = CRITICAL_REGRESSION",
    report_dict_crit.get("verdict") == "CRITICAL_REGRESSION",
    f"got {report_dict_crit.get('verdict')}",
)
test(
    "Dict breakdown CRITICAL: regressions list populated",
    len(report_dict_crit.get("regressions", [])) > 0,
)

# 17e. Mixed: one side dict, other side flat floats — must work without crash
report_mixed = _run_comparator(
    _make_dict_breakdown_scores(8.0, 8.5, 8.0, 7.5, 8.0),
    _make_scores(7.0, 7.0, 7.0, 7.0, 7.0),            # flat floats
)
test(
    "Mixed breakdown (dict v_new, float v_current): does not crash",
    isinstance(report_mixed, dict),
)
test(
    "Mixed breakdown: produces a verdict",
    "verdict" in report_mixed,
)

# 17f. Direct unit test: compare_dimensions node with dict-shaped breakdown
if _comparator_imported:
    cd_dict_state: ComparatorState = {
        "v_new_id": "v_dict",
        "v_current_id": "v_flat",
        "v_new_scores": _make_dict_breakdown_scores(8.0, 8.0, 8.0, 8.0, 8.0),
        "v_current_scores": _make_scores(7.0, 7.0, 7.0, 7.0, 7.0),
        "v_new_quality_score": 8.0,
        "v_current_quality_score": 7.0,
        "v_new_breakdown": {
            "task_completion": {"score": 8.0, "weight": 0.35, "raw_value": 8.0},
            "output_quality": {"score": 8.0, "weight": 0.35, "raw_value": 8.0},
            "latency": {"score": 8.0, "weight": 0.15, "raw_value": 8.0},
            "cost_efficiency": {"score": 8.0, "weight": 0.15, "raw_value": 8.0},
        },
        "v_current_breakdown": {
            "task_completion": 7.0, "output_quality": 7.0,
            "latency": 7.0, "cost_efficiency": 7.0,
        },
        "thresholds": _DEFAULT_THRESHOLDS,
        "errors": [],
    }
    cd_dict_result = compare_dimensions(cd_dict_state)
    test(
        "compare_dimensions unit: dict v_new breakdown delta = 1.0 each",
        all(abs(v - 1.0) < 0.001 for v in cd_dict_result.get("deltas", {}).values()),
        f"deltas={cd_dict_result.get('deltas')}",
    )
    test(
        "compare_dimensions unit: overall_delta = 1.0",
        cd_dict_result.get("overall_delta") == 1.0,
        f"got {cd_dict_result.get('overall_delta')}",
    )
else:
    test("compare_dimensions unit: skipped (import failed)", False)
    test("compare_dimensions unit: skipped (import failed)", False)


# ============================================================================
# TEST SECTION 18: Nested quality_score dict in compare_versions_node (Fix P1-2)
# ============================================================================
#
# EvalRunnerState.quality_score is typed dict[str, Any] with shape:
#   {"quality_score": float, "breakdown": {dim: {score, weight, raw_value}}, ...}
# The original compare_versions_node passed this whole dict as the quality_score
# float.  The fix extracts qs_dict.get("quality_score") and qs_dict.get("breakdown").
#
print("\n== SECTION 18: Nested quality_score in compare_versions_node (Fix P1-2) ==")

with patch.dict(os.environ, {"STORAGE_DATA_DIR": _decision_tmp}):
    # 18a. Nested quality_score dict as emitted by eval runner
    nested_qs_state = {
        "run_id": "cvn_nested_001",
        "version_id": "v_nested_qs",
        "eval_result": {
            "version_id": "v_nested_qs",
            "quality_score": {
                "quality_score": 8.5,
                "breakdown": {
                    "task_completion": {"score": 9.0, "weight": 0.35, "raw_value": 9.0},
                    "output_quality": {"score": 8.5, "weight": 0.35, "raw_value": 8.5},
                    "latency": {"score": 8.0, "weight": 0.15, "raw_value": 8.0},
                    "cost_efficiency": {"score": 8.0, "weight": 0.15, "raw_value": 8.0},
                },
                "metadata": {},
                "warnings": [],
            },
        },
        "quality_score": 8.5,
        "errors": [],
    }
    nested_result = compare_versions_node(nested_qs_state) if _orch_imported else {}
    test(
        "Nested quality_score: does not crash",
        isinstance(nested_result.get("comparison_report"), dict),
    )
    nested_report = nested_result.get("comparison_report", {})
    test(
        "Nested quality_score: report has verdict",
        "verdict" in nested_report,
    )
    # No promoted version in storage → first deployment → IMPROVED
    test(
        "Nested quality_score: first deploy = IMPROVED",
        nested_report.get("verdict") == "IMPROVED",
        f"got {nested_report.get('verdict')}",
    )
    # Delta should be based on 8.5 (extracted score), not 0 or dict repr
    test(
        "Nested quality_score: delta = 8.5 (vs baseline 0.0)",
        nested_report.get("delta") == 8.5,
        f"got delta={nested_report.get('delta')}",
    )

    # 18b. Flat quality_score float (backward-compat path still works)
    flat_qs_state = {
        "run_id": "cvn_flat_001",
        "version_id": "v_flat_qs",
        "eval_result": {
            "version_id": "v_flat_qs",
            "quality_score": 7.5,                 # plain float
            "score_breakdown": {
                "task_completion": 7.5, "output_quality": 7.5,
                "latency": 7.5, "cost_efficiency": 7.5,
            },
        },
        "quality_score": 7.5,
        "errors": [],
    }
    flat_result = compare_versions_node(flat_qs_state) if _orch_imported else {}
    test(
        "Flat quality_score still works after fix",
        isinstance(flat_result.get("comparison_report"), dict),
    )
    test(
        "Flat quality_score: delta = 7.5 (vs baseline 0.0)",
        flat_result.get("comparison_report", {}).get("delta") == 7.5,
        f"got {flat_result.get('comparison_report', {}).get('delta')}",
    )


# ============================================================================
# CLEANUP & SUMMARY
# ============================================================================

# Clean up temp directory
try:
    shutil.rmtree(_decision_tmp, ignore_errors=True)
except Exception:
    pass

print(f"\n{'='*60}")
print(f"Phase 3 Results:  {_pass_count} passed, {_fail_count} failed")
print(f"{'='*60}")

if _fail_count > 0:
    sys.exit(1)
