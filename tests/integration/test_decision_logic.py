from __future__ import annotations

from agents.decision.agent import (
    apply_rules,
    DECISION_AUTO_PROMOTE,
    DECISION_NO_ACTION,
    DECISION_ESCALATE,
    DECISION_ROLLBACK,
)


def test_auto_promote():
    out = apply_rules(
        {
            "comparison_report": {
                "verdict": "IMPROVED",
                "delta": 0.5,
                "improvements": [{"dimension": "task_completion"}],
                "regressions": [],
                "thresholds_used": {},
            }
        }
    )
    assert out["decision"] == DECISION_AUTO_PROMOTE
    assert "Quality score improved" in out["reasoning"]


def test_no_action():
    out = apply_rules(
        {
            "comparison_report": {
                "verdict": "NO_SIGNIFICANT_CHANGE",
                "delta": -0.2,
                "improvements": [],
                "regressions": [],
                "thresholds_used": {},
            }
        }
    )
    assert out["decision"] == DECISION_NO_ACTION


def test_escalate_on_regression_detected():
    out = apply_rules(
        {
            "comparison_report": {
                "verdict": "REGRESSION_DETECTED",
                "delta": -0.7,
                "improvements": [],
                "regressions": [
                    {"dimension": "latency", "old": 9.0, "new": 7.0, "delta": -2.0}
                ],
                "thresholds_used": {"escalate_threshold": -0.5, "rollback_threshold": -1.0},
            }
        }
    )
    assert out["decision"] == DECISION_ESCALATE


def test_rollback_on_critical_regression():
    out = apply_rules(
        {
            "comparison_report": {
                "verdict": "CRITICAL_REGRESSION",
                "delta": -1.5,
                "improvements": [],
                "regressions": [
                    {"dimension": "latency", "old": 9.0, "new": 7.0, "delta": -2.0},
                    {"dimension": "cost_efficiency", "old": 9.0, "new": 8.5, "delta": -0.5},
                ],
                "thresholds_used": {"rollback_threshold": -1.0},
            }
        }
    )
    assert out["decision"] == DECISION_ROLLBACK
    assert "Critical regression" in out["reasoning"]

