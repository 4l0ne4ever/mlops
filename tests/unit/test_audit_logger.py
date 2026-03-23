from __future__ import annotations

import builtins
import json
import re
from datetime import datetime, timezone

from agents.eval_runner.audit_logger import JudgeAuditLogger


def test_get_summary_empty(tmp_path):
    logger = JudgeAuditLogger(audit_dir=tmp_path)
    summary = logger.get_summary()
    assert summary == {"total_calls": 0}


def test_log_and_read_back_and_filter_by_run_id(tmp_path):
    logger = JudgeAuditLogger(audit_dir=tmp_path)

    run_a = "run_a"
    run_b = "run_b"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logger.log_call(
        run_id=run_a,
        test_case_id="tc1",
        prompt_variant="A",
        model_name="m",
        temperature=0.0,
        pass_num=1,
        attempt_num=1,
        input_text="in",
        expected_output="exp",
        actual_output="act",
        raw_response="{}",
        parsed_result={"score": 1},
        latency_ms=12.34,
        success=True,
        error="",
    )
    logger.log_call(
        run_id=run_b,
        test_case_id="tc2",
        prompt_variant="A",
        model_name="m",
        temperature=0.0,
        pass_num=1,
        attempt_num=1,
        input_text="in",
        expected_output="exp",
        actual_output="act",
        raw_response="{}",
        parsed_result={"score": 1},
        latency_ms=9.87,
        success=False,
        error="boom",
    )

    calls_a = logger.get_calls(date=today, run_id=run_a)
    calls_b = logger.get_calls(date=today, run_id=run_b)

    assert len(calls_a) == 1
    assert calls_a[0]["run_id"] == run_a
    assert calls_a[0]["success"] is True

    assert len(calls_b) == 1
    assert calls_b[0]["run_id"] == run_b
    assert calls_b[0]["success"] is False


def test_daily_rotation_file_name_format(tmp_path):
    logger = JudgeAuditLogger(audit_dir=tmp_path)
    logger.log_call(run_id="r", test_case_id="tc1")

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert re.match(r"^\d{4}-\d{2}-\d{2}\.jsonl$", files[0].name) is not None


def test_get_summary_stats(tmp_path):
    logger = JudgeAuditLogger(audit_dir=tmp_path)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for i in range(10):
        logger.log_call(
            run_id="r1",
            test_case_id=f"tc{i}",
            success=(i < 8),
            latency_ms=float(i),
            error="" if i < 8 else "err",
        )

    summary = logger.get_summary(date=today)
    assert summary["total_calls"] == 10
    assert summary["success_rate"] == 0.8


def test_log_failure_is_silent(tmp_path, monkeypatch):
    logger = JudgeAuditLogger(audit_dir=tmp_path)

    original_open = builtins.open

    def _boom(*args, **kwargs):
        raise PermissionError("nope")

    monkeypatch.setattr(builtins, "open", _boom)
    try:
        logger.log_call(run_id="r1", test_case_id="tc1", success=True)
    finally:
        monkeypatch.setattr(builtins, "open", original_open)

    # If log_call raised, the test would fail; reaching here means it was silent.
    assert True

