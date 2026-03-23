from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import EvalRunResult, QualityScore
from ..config import get_config


@dataclass(frozen=True)
class EvalRunnerConfig:
    run_id: str | None = None
    version_id: str | None = None
    test_suite_path: str | None = None
    target_app_url: str | None = None


class EvalRunner:
    """
    Public wrapper around the internal Eval Runner state graph.
    """

    def run_eval(self, *, cfg: EvalRunnerConfig | None = None, version_id: str = "", test_suite_path: str = "", target_app_url: str = "", run_id: str = "") -> EvalRunResult:
        runtime = get_config()
        cfg = cfg or EvalRunnerConfig()

        run_id_final = run_id or cfg.run_id or str(uuid.uuid4())
        version_id_final = version_id or cfg.version_id or "v_unknown"
        test_suite_final = test_suite_path or cfg.test_suite_path or runtime.test_suite_path
        target_app_final = target_app_url or cfg.target_app_url or runtime.target_app_url

        # Delegate to existing implementation
        from agents.eval_runner.agent import run_eval as _run_eval

        result_dict = _run_eval(
            version_id=version_id_final,
            test_suite_path=str(test_suite_final),
            target_app_url=str(target_app_final),
            run_id=run_id_final,
        )

        quality_score_dict: dict[str, Any] = result_dict.get("quality_score", {}) or {}
        qs = QualityScore(
            quality_score=float(quality_score_dict.get("quality_score", 0.0)),
            breakdown=quality_score_dict.get("breakdown", {}) or {},
            metadata=quality_score_dict.get("metadata", {}) or {},
            warnings=quality_score_dict.get("warnings", []) or [],
        )

        status = result_dict.get("status", "completed") or "completed"
        return EvalRunResult(
            run_id=result_dict.get("run_id", run_id_final),
            version_id=version_id_final,
            quality_score=qs,
            status=status,
            result_id=result_dict.get("result_id"),
            raw=result_dict,
        )

