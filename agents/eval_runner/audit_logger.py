"""
Judge Call Audit Logger — Persists every LLM judge call for post-hoc audit.

Per P2-4: "Log mọi LLM judge call để audit sau"

Each judge call is logged as a JSON record with:
    - timestamp, run_id, test_case_id
    - prompt variant used
    - model, temperature, pass number, attempt number
    - input/output/expected text
    - raw LLM response
    - parsed scores
    - latency_ms, success/failure status

Audit logs are saved to .local-data/audit-logs/judge-calls/{date}.jsonl
(one JSON object per line for efficient streaming/grep).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class JudgeAuditLogger:
    """
    Append-only audit logger for LLM judge calls.

    Thread-safety note:
        Uses file append mode ("a") which is atomic for writes < PIPE_BUF
        (4096 bytes) on Linux/macOS per POSIX spec. Each JSONL record is
        typically ~1-3 KB, well within this limit.

        WARNING: This assumption does NOT hold on Windows or on NFS-mounted
        volumes where append is not guaranteed atomic. If deploying to
        containers with shared volumes (e.g. EFS, NFS), consider switching
        to a proper database or adding file-level locking (fcntl/flock).
    """

    # Default truncation limit for text fields in audit records.
    # Set higher if you need full text for reproducing judge calls.
    DEFAULT_TEXT_TRUNCATION = 1000

    def __init__(
        self,
        audit_dir: str | Path | None = None,
        text_truncation: int | None = None,
    ) -> None:
        if audit_dir:
            self._audit_dir = Path(audit_dir)
        else:
            data_dir = os.environ.get(
                "STORAGE_DATA_DIR", str(_PROJECT_ROOT / ".local-data")
            )
            self._audit_dir = Path(data_dir) / "audit-logs" / "judge-calls"
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        self._text_truncation = (
            text_truncation
            if text_truncation is not None
            else self.DEFAULT_TEXT_TRUNCATION
        )

    def _get_log_path(self) -> Path:
        """Get today's log file path."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._audit_dir / f"{date_str}.jsonl"

    def log_call(
        self,
        *,
        run_id: str = "",
        test_case_id: str = "",
        prompt_variant: str = "",
        model_name: str = "",
        temperature: float = 0.0,
        pass_num: int = 0,
        attempt_num: int = 0,
        input_text: str = "",
        expected_output: str = "",
        actual_output: str = "",
        raw_response: str = "",
        parsed_result: dict[str, Any] | None = None,
        latency_ms: float = 0.0,
        success: bool = True,
        error: str = "",
    ) -> None:
        """
        Log a single judge call to the audit file.

        Args:
            run_id: Eval run identifier.
            test_case_id: Test case being evaluated.
            prompt_variant: Which prompt variant (A, B, C).
            model_name: LLM model used.
            temperature: Temperature setting.
            pass_num: Which judge pass (1, 2, ...).
            attempt_num: Retry attempt number.
            input_text: Source text being evaluated.
            expected_output: Reference translation.
            actual_output: Translation being scored.
            raw_response: Raw LLM response text.
            parsed_result: Parsed JSON scores (if successful).
            latency_ms: LLM call latency.
            success: Whether the call succeeded.
            error: Error message if failed.
        """
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "test_case_id": test_case_id,
            "prompt_variant": prompt_variant,
            "model": model_name,
            "temperature": temperature,
            "pass_num": pass_num,
            "attempt_num": attempt_num,
            "input_text": input_text[:self._text_truncation],
            "expected_output": expected_output[:self._text_truncation],
            "actual_output": actual_output[:self._text_truncation],
            "raw_response": raw_response[:2000],
            "parsed_result": parsed_result,
            "latency_ms": round(latency_ms, 2),
            "success": success,
            "error": error,
        }

        try:
            log_path = self._get_log_path()
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Failed to write audit log: %s", exc)

    def get_calls(
        self,
        date: str = "",
        run_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Read audit log entries.

        Args:
            date: Date string (YYYY-MM-DD). Defaults to today.
            run_id: Filter by run_id.
            limit: Max entries to return.

        Returns:
            List of audit log records.
        """
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        log_path = self._audit_dir / f"{date}.jsonl"
        if not log_path.exists():
            return []

        results: list[dict[str, Any]] = []
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    if run_id and record.get("run_id") != run_id:
                        continue
                    results.append(record)
                    if len(results) >= limit:
                        break
        except Exception as exc:
            logger.warning("Failed to read audit log: %s", exc)

        return results

    def get_summary(self, date: str = "") -> dict[str, Any]:
        """
        Get summary statistics for a day's audit logs.

        Returns:
            Dict with total_calls, success_rate, avg_latency, etc.
        """
        calls = self.get_calls(date=date, limit=10000)
        if not calls:
            return {"total_calls": 0}

        successes = [c for c in calls if c.get("success")]
        latencies = [c["latency_ms"] for c in successes if c.get("latency_ms")]

        return {
            "total_calls": len(calls),
            "successful": len(successes),
            "failed": len(calls) - len(successes),
            "success_rate": round(len(successes) / len(calls), 3) if calls else 0,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
            "unique_runs": len(set(c.get("run_id", "") for c in calls)),
            "unique_test_cases": len(set(c.get("test_case_id", "") for c in calls)),
        }
