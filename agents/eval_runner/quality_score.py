"""
Quality Score Calculator — computes weighted composite quality score.

Implements the formula from configs/quality_score_spec.md:
    QualityScore = Σ(weight_i × normalized_score_i)

Four dimensions:
    1. Task Completion Rate (0.35) — % test cases passing threshold
    2. Output Quality (0.35) — average LLM-as-judge score
    3. Latency (0.20) — normalized response time
    4. Cost Efficiency (0.10) — normalized cost per request

All parameters configurable via configs/thresholds.json.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default weights / thresholds (overridden by configs/thresholds.json)
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS = {
    "task_completion": 0.35,
    "output_quality": 0.35,
    "latency": 0.20,
    "cost_efficiency": 0.10,
}

_DEFAULT_PASS_THRESHOLD = 6.0
_DEFAULT_MIN_TEST_CASES_REQUIRED = 0.5  # fraction


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DimensionScore:
    """A single quality dimension's score and weight."""
    name: str
    raw_value: float
    normalized_score: float
    weight: float
    weighted_score: float


@dataclass
class QualityScoreResult:
    """Complete quality score output with breakdown."""
    quality_score: float
    breakdown: dict[str, dict[str, float]]
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict matching the spec output format."""
        return {
            "quality_score": round(self.quality_score, 3),
            "breakdown": {
                name: {
                    "score": round(info["score"], 3),
                    "weight": info["weight"],
                    "raw_value": info.get("raw_value", 0),
                }
                for name, info in self.breakdown.items()
            },
            "metadata": self.metadata,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------

class QualityScoreCalculator:
    """
    Computes a composite Quality Score (0-10) from eval run results.

    Usage:
        calc = QualityScoreCalculator.from_config_file("configs/thresholds.json")
        result = calc.calculate(
            test_case_scores=[7.5, 8.0, 3.0, 9.1, ...],
            latencies_ms=[1200, 1500, 1000, ...],
            costs_usd=[0.002, 0.003, 0.002, ...],
        )
        print(result.quality_score)  # e.g. 8.36
    """

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        pass_threshold: float = _DEFAULT_PASS_THRESHOLD,
        min_test_cases_required: float = _DEFAULT_MIN_TEST_CASES_REQUIRED,
    ) -> None:
        self._weights = weights or dict(_DEFAULT_WEIGHTS)
        self._pass_threshold = pass_threshold
        self._min_test_cases_required = min_test_cases_required

        # Validate weights sum to ~1.0
        total = sum(self._weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Dimension weights must sum to 1.0, got {total:.3f}"
            )

    @classmethod
    def from_config_file(cls, config_path: str | Path) -> "QualityScoreCalculator":
        """Create a QualityScoreCalculator from a thresholds.json config file."""
        path = Path(config_path)
        if not path.exists():
            logger.warning(
                "Config file %s not found, using defaults", config_path
            )
            return cls()

        config = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            weights=config.get("per_dimension_weights"),
            pass_threshold=config.get(
                "test_case_pass_threshold", _DEFAULT_PASS_THRESHOLD
            ),
            min_test_cases_required=config.get(
                "min_test_cases_required", _DEFAULT_MIN_TEST_CASES_REQUIRED
            ),
        )

    # -- Normalization formulas (from quality_score_spec.md) -----------------

    @staticmethod
    def normalize_task_completion(pass_rate_pct: float) -> float:
        """Normalize task completion rate: score = raw_percentage / 10."""
        return min(max(pass_rate_pct, 0.0), 100.0) / 10.0

    @staticmethod
    def normalize_output_quality(avg_judge_score: float) -> float:
        """Normalize output quality: direct use (already 0-10)."""
        return min(max(avg_judge_score, 0.0), 10.0)

    @staticmethod
    def normalize_latency(avg_latency_ms: float) -> float:
        """Normalize latency: score = 10 - min(avg_latency_ms / 1000, 10)."""
        return 10.0 - min(avg_latency_ms / 1000.0, 10.0)

    @staticmethod
    def normalize_cost(cost_per_request_usd: float) -> float:
        """Normalize cost: score = 10 - min(cost × 100, 10)."""
        return 10.0 - min(cost_per_request_usd * 100.0, 10.0)

    # -- Main calculation ----------------------------------------------------

    def calculate(
        self,
        test_case_scores: list[float],
        latencies_ms: list[float],
        costs_usd: list[float],
        total_cases: int | None = None,
        skipped_cases: int = 0,
        version_id: str = "",
        run_id: str = "",
    ) -> QualityScoreResult:
        """
        Calculate Quality Score from raw eval results.

        Args:
            test_case_scores: LLM-as-judge scores for each test case (0-10).
            latencies_ms: Response time in milliseconds for each test case.
            costs_usd: Cost in USD for each test case.
            total_cases: Total number of test cases (including skipped).
                         Defaults to len(test_case_scores) + skipped_cases.
            skipped_cases: Number of test cases that were skipped.
            version_id: Version identifier for metadata.
            run_id: Run identifier for metadata.

        Returns:
            QualityScoreResult with composite score and breakdown.
        """
        warnings: list[str] = []

        if total_cases is None:
            total_cases = len(test_case_scores) + skipped_cases

        # --- Validate minimum test cases ---
        actual_run = len(test_case_scores)
        # Initialize early to avoid UnboundLocalError on refactor
        passed = 0
        pass_rate_pct = 0.0

        if total_cases > 0:
            run_fraction = actual_run / total_cases
            if run_fraction < self._min_test_cases_required:
                warnings.append(
                    f"Only {actual_run}/{total_cases} "
                    f"({run_fraction:.0%}) test cases completed. "
                    f"Minimum required: {self._min_test_cases_required:.0%}. "
                    f"Eval run may need human review."
                )

        # --- Dimension 1: Task Completion Rate ---
        if actual_run > 0:
            passed = sum(1 for s in test_case_scores if s >= self._pass_threshold)
            pass_rate_pct = (passed / actual_run) * 100.0
        task_completion_score = self.normalize_task_completion(pass_rate_pct)

        # --- Dimension 2: Output Quality ---
        if actual_run > 0:
            avg_judge_score = sum(test_case_scores) / actual_run
        else:
            avg_judge_score = 0.0
        output_quality_score = self.normalize_output_quality(avg_judge_score)

        # --- Dimension 3: Latency ---
        # When no latency data (e.g. app down, all test cases failed),
        # penalize with score=0 instead of rewarding with score=10.
        if latencies_ms:
            avg_latency_ms = sum(latencies_ms) / len(latencies_ms)
            latency_score = self.normalize_latency(avg_latency_ms)
        else:
            avg_latency_ms = None
            latency_score = 0.0  # No data → penalize, not reward

        # --- Dimension 4: Cost Efficiency ---
        # Same logic: no cost data means we have nothing to evaluate,
        # not that costs were zero (free).
        if costs_usd:
            avg_cost = sum(costs_usd) / len(costs_usd)
            cost_score = self.normalize_cost(avg_cost)
        else:
            avg_cost = None
            cost_score = 0.0  # No data → penalize, not reward

        # --- Weighted composite ---
        breakdown = {
            "task_completion": {
                "score": task_completion_score,
                "weight": self._weights["task_completion"],
                "raw_value": pass_rate_pct,
            },
            "output_quality": {
                "score": output_quality_score,
                "weight": self._weights["output_quality"],
                "raw_value": avg_judge_score,
            },
            "latency": {
                "score": latency_score,
                "weight": self._weights["latency"],
                "raw_value": avg_latency_ms if avg_latency_ms is not None else 0.0,
                "no_data": avg_latency_ms is None,
            },
            "cost_efficiency": {
                "score": cost_score,
                "weight": self._weights["cost_efficiency"],
                "raw_value": avg_cost if avg_cost is not None else 0.0,
                "no_data": avg_cost is None,
            },
        }

        quality_score = sum(
            breakdown[dim]["score"] * breakdown[dim]["weight"]
            for dim in breakdown
        )

        metadata = {}
        if version_id:
            metadata["version_id"] = version_id
        if run_id:
            metadata["run_id"] = run_id
        metadata["total_test_cases"] = total_cases
        metadata["completed_test_cases"] = actual_run
        metadata["passed_test_cases"] = passed
        metadata["skipped_test_cases"] = skipped_cases

        logger.info(
            "Quality Score calculated: %.3f (TC=%.1f OQ=%.1f L=%.1f CE=%.1f)",
            quality_score,
            task_completion_score,
            output_quality_score,
            latency_score,
            cost_score,
        )

        return QualityScoreResult(
            quality_score=quality_score,
            breakdown=breakdown,
            metadata=metadata,
            warnings=warnings,
        )
