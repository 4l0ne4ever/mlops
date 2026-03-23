from __future__ import annotations

import pytest

from agents.eval_runner.evaluator import (
    DEFAULT_PROMPT_VARIANT,
    LLMJudgeEvaluator,
)


def test_parse_valid_json():
    text = '{"score": 8.3, "accuracy": 8.5, "fluency": 8.1, "completeness": 7.9, "reasoning": "ok", "issues": []}'
    parsed = LLMJudgeEvaluator._parse_json_response(text)
    assert parsed is not None
    assert parsed["score"] == 8.3
    assert parsed["accuracy"] == 8.5


def test_parse_json_in_markdown_code_block():
    text = """
```json
{"score": 8.3, "accuracy": 8.5, "fluency": 8.1, "completeness": 7.9, "reasoning": "ok", "issues": []}
```
"""
    parsed = LLMJudgeEvaluator._parse_json_response(text)
    assert parsed is not None
    assert parsed["score"] == 8.3


def test_parse_missing_fields_returns_none():
    text = '{"accuracy": 8.5, "fluency": 8.1, "completeness": 7.9}'
    parsed = LLMJudgeEvaluator._parse_json_response(text)
    assert parsed is None


def test_parse_scores_are_clamped_to_0_10():
    text = '{"score": 15, "accuracy": -1, "fluency": 11, "completeness": 0}'
    parsed = LLMJudgeEvaluator._parse_json_response(text)
    assert parsed is not None
    assert parsed["score"] == 10.0
    assert parsed["accuracy"] == 0.0
    assert parsed["fluency"] == 10.0
    assert parsed["completeness"] == 0.0


def test_prompt_variant_fallback_to_default():
    evaluator = LLMJudgeEvaluator(prompt_variant="__not-exist__")
    assert evaluator._prompt_variant == DEFAULT_PROMPT_VARIANT


def test_anomaly_detected_when_score_range_exceeds_threshold(monkeypatch):
    evaluator = LLMJudgeEvaluator(num_passes=2, anomaly_threshold=1.5, prompt_variant="A")
    monkeypatch.setattr(evaluator, "_ensure_client", lambda: None)

    # Pass 1 => 9.0, Pass 2 => 3.0 => range 6.0 > 1.5 => anomaly True
    def _fake_single_pass(user_prompt, pass_num, **kwargs):
        if pass_num == 1:
            return {
                "score": 9.0,
                "accuracy": 9.0,
                "fluency": 9.0,
                "completeness": 9.0,
                "reasoning": "r1",
                "issues": [],
            }
        return {
            "score": 3.0,
            "accuracy": 3.0,
            "fluency": 3.0,
            "completeness": 3.0,
            "reasoning": "r2",
            "issues": ["i"],
        }

    monkeypatch.setattr(evaluator, "_single_pass", _fake_single_pass)

    judge_result = evaluator.evaluate(
        input_text="a",
        expected_output="b",
        actual_output="c",
        source_lang="en",
        target_lang="vi",
        run_id="r1",
        test_case_id="tc1",
    )
    assert judge_result.anomaly is True


def test_no_anomaly_when_score_range_within_threshold(monkeypatch):
    evaluator = LLMJudgeEvaluator(num_passes=2, anomaly_threshold=10.0, prompt_variant="A")
    monkeypatch.setattr(evaluator, "_ensure_client", lambda: None)

    def _fake_single_pass(user_prompt, pass_num, **kwargs):
        return {
            "score": 8.0 if pass_num == 1 else 8.5,
            "accuracy": 8.0,
            "fluency": 8.0,
            "completeness": 8.0,
            "reasoning": "ok",
            "issues": [],
        }

    monkeypatch.setattr(evaluator, "_single_pass", _fake_single_pass)

    judge_result = evaluator.evaluate(
        input_text="a",
        expected_output="b",
        actual_output="c",
        source_lang="en",
        target_lang="vi",
        run_id="r1",
        test_case_id="tc1",
    )
    assert judge_result.anomaly is False


def test_all_passes_fail_returns_zero_score_and_anomaly_true(monkeypatch):
    evaluator = LLMJudgeEvaluator(num_passes=2, anomaly_threshold=1.5, prompt_variant="A")
    monkeypatch.setattr(evaluator, "_ensure_client", lambda: None)

    monkeypatch.setattr(evaluator, "_single_pass", lambda *args, **kwargs: None)

    judge_result = evaluator.evaluate(
        input_text="a",
        expected_output="b",
        actual_output="c",
        source_lang="en",
        target_lang="vi",
        run_id="r1",
        test_case_id="tc1",
    )
    assert judge_result.score == 0.0
    assert judge_result.anomaly is True


def test_average_across_passes():
    evaluator = LLMJudgeEvaluator(num_passes=2, anomaly_threshold=100.0, prompt_variant="A")
    # Avoid Gemini client creation
    evaluator._ensure_client = lambda: None

    def _fake_single_pass(user_prompt, pass_num, **kwargs):
        return {
            "score": 7.0 if pass_num == 1 else 9.0,
            "accuracy": 7.0 if pass_num == 1 else 9.0,
            "fluency": 7.0 if pass_num == 1 else 9.0,
            "completeness": 7.0 if pass_num == 1 else 9.0,
            "reasoning": "ok",
            "issues": [],
        }

    evaluator._single_pass = _fake_single_pass

    judge_result = evaluator.evaluate(
        input_text="a",
        expected_output="b",
        actual_output="c",
        source_lang="en",
        target_lang="vi",
        run_id="r1",
        test_case_id="tc1",
    )
    assert judge_result.score == 8.0

