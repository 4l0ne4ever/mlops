from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from .types import OrchestratorResult
from ..config import get_config


@dataclass(frozen=True)
class OrchestratorConfig:
    run_id: str | None = None
    test_suite_path: str | None = None
    trigger_type: Literal["manual", "webhook"] = "manual"
    webhook_payload: dict[str, Any] | None = None


class Orchestrator:
    """
    Public wrapper around the internal Orchestrator state graph.
    """

    def run_pipeline(
        self,
        *,
        cfg: OrchestratorConfig | None = None,
        run_id: str = "",
        trigger_type: Literal["manual", "webhook"] = "manual",
        webhook_payload: dict[str, Any] | None = None,
        test_suite_path: str = "",
    ) -> OrchestratorResult:
        runtime = get_config()
        cfg = cfg or OrchestratorConfig()

        run_id_final = run_id or cfg.run_id or str(uuid.uuid4())
        trigger_type_final = cfg.trigger_type or trigger_type
        webhook_payload_final = webhook_payload if webhook_payload is not None else cfg.webhook_payload
        test_suite_final = test_suite_path or cfg.test_suite_path or runtime.test_suite_path

        from agents.orchestrator.agent import run_pipeline as _run_pipeline

        result_dict = _run_pipeline(
            trigger_type=trigger_type_final,
            webhook_payload=webhook_payload_final,
            run_id=run_id_final,
            test_suite_path=test_suite_final,
        )

        return OrchestratorResult(
            run_id=result_dict.get("run_id", run_id_final),
            status=result_dict.get("status", "completed") or "completed",
            quality_score=float(result_dict.get("quality_score", 0.0) or 0.0),
            comparison_report=result_dict.get("comparison_report", {}) or {},
            decision=result_dict.get("decision", {}) or {},
            raw=result_dict,
        )

