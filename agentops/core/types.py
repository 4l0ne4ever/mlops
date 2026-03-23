from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QualityScore:
    quality_score: float
    breakdown: dict[str, Any]
    metadata: dict[str, Any]
    warnings: list[str]


@dataclass(frozen=True)
class EvalRunResult:
    run_id: str
    version_id: str
    quality_score: QualityScore
    status: str
    result_id: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class OrchestratorResult:
    run_id: str
    status: str
    quality_score: float
    comparison_report: dict[str, Any]
    decision: dict[str, Any]
    raw: dict[str, Any] | None = None

