from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import time

import httpx
import pytest

from agents.eval_runner.agent import (
    aggregate_results,
    evaluate_outputs,
    load_test_suite,
    run_test_cases,
    save_results,
)
from agents.eval_runner.evaluator import JudgeResult, LLMJudgeEvaluator


@dataclass
class _FakeResponse:
    status_code: int
    text: str
    _json: dict

    def json(self) -> dict:
        return self._json


def _write_suite(tmp_path: Path, cases: list[dict]) -> Path:
    p = tmp_path / "suite.json"
    p.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    return p


def test_happy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_CONFIG", "configs/local.json")
    monkeypatch.setenv("MCP_ALLOW_FALLBACK", "1")
    monkeypatch.setenv("STORAGE_DATA_DIR", str(tmp_path / "storage"))

    cases = [
        {
            "id": f"tc-{i}",
            "category": "simple_sentence",
            "source_lang": "en",
            "target_lang": "vi",
            "input": f"ok-input-{i}",
            "expected_output": f"expected-{i}",
        }
        for i in range(6)
    ]
    suite_path = _write_suite(tmp_path, cases)

    async def fake_post(self, url, json=None, **kwargs):
        payload_text = (json or {}).get("text", "")
        # Return a deterministic shape expected by run_test_cases.
        return _FakeResponse(
            status_code=200,
            text="OK",
            _json={
                "translated_text": payload_text,
                "estimated_cost_usd": 0.001,
                "token_count": 100,
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post, raising=True)

    def fake_evaluate(self, **kwargs):
        return JudgeResult(
            score=8.0,
            accuracy=8.0,
            fluency=8.0,
            completeness=8.0,
            reasoning="ok",
            issues=[],
            anomaly=False,
        )

    monkeypatch.setattr(LLMJudgeEvaluator, "evaluate", fake_evaluate, raising=True)

    # Avoid local backend writes while still running nodes.
    from agents import mcp_client as _mcp_client

    def fake_save_eval_result(self, run_id, version_id, scores, details):
        return {"result_id": "res-happy", "timestamp": time.time()}

    monkeypatch.setattr(
        _mcp_client.MCPStorageClient,
        "save_eval_result",
        fake_save_eval_result,
        raising=True,
    )

    state = {
        "run_id": "run-happy",
        "version_id": "v1",
        "test_suite_path": str(suite_path),
        "target_app_url": "http://fake-target",
        "errors": [],
    }

    load_out = load_test_suite(state)
    test_cases = load_out["test_cases"]
    assert len(test_cases) == 6

    run_out = run_test_cases({**state, "test_cases": test_cases})
    assert len(run_out["test_results"]) == 6

    eval_out = evaluate_outputs({**state, "test_results": run_out["test_results"]})
    assert len(eval_out["judge_results"]) == 6

    agg_out = aggregate_results(
        {
            **state,
            "judge_results": eval_out["judge_results"],
            "test_results": run_out["test_results"],
            "errors": [],
        }
    )
    assert agg_out["quality_score"]["quality_score"] > 7.0

    save_out = save_results(
        {
            **state,
            "quality_score": agg_out["quality_score"],
            "judge_results": eval_out["judge_results"],
            "test_results": run_out["test_results"],
            "errors": [],
        }
    )
    assert save_out["status"] == "completed"
    assert save_out["result_id"] == "res-happy"


def test_target_app_down_produces_low_quality_score(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_CONFIG", "configs/local.json")
    monkeypatch.setenv("MCP_ALLOW_FALLBACK", "1")
    monkeypatch.setenv("STORAGE_DATA_DIR", str(tmp_path / "storage"))

    cases = [
        {
            "id": f"tc-{i}",
            "category": "simple_sentence",
            "source_lang": "en",
            "target_lang": "vi",
            "input": f"down-{i}",
            "expected_output": f"expected-{i}",
        }
        for i in range(5)
    ]
    suite_path = _write_suite(tmp_path, cases)

    async def fake_post(self, url, json=None, **kwargs):
        return _FakeResponse(status_code=503, text="Service Unavailable", _json={})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post, raising=True)

    from agents import mcp_client as _mcp_client

    monkeypatch.setattr(
        _mcp_client.MCPStorageClient,
        "save_eval_result",
        lambda *args, **kwargs: {"result_id": "res-down", "timestamp": time.time()},
        raising=True,
    )

    state = {
        "run_id": "run-down",
        "version_id": "v1",
        "test_suite_path": str(suite_path),
        "target_app_url": "http://fake-target",
        "errors": [],
    }

    test_cases = load_test_suite(state)["test_cases"]
    run_out = run_test_cases({**state, "test_cases": test_cases})
    eval_out = evaluate_outputs({**state, "test_results": run_out["test_results"]})
    agg_out = aggregate_results(
        {
            **state,
            "judge_results": eval_out["judge_results"],
            "test_results": run_out["test_results"],
            "errors": [],
        }
    )

    assert agg_out["quality_score"]["quality_score"] < 1.0


def test_partial_failures_skip_judge_and_remain_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_CONFIG", "configs/local.json")
    monkeypatch.setenv("MCP_ALLOW_FALLBACK", "1")
    monkeypatch.setenv("STORAGE_DATA_DIR", str(tmp_path / "storage"))

    # 6 cases => complete first 3, fail last 3
    cases = []
    for i in range(6):
        prefix = "ok" if i < 3 else "fail"
        cases.append(
            {
                "id": f"tc-{i}",
                "category": "simple_sentence",
                "source_lang": "en",
                "target_lang": "vi",
                "input": f"{prefix}-{i}",
                "expected_output": f"expected-{i}",
            }
        )

    suite_path = _write_suite(tmp_path, cases)

    async def fake_post(self, url, json=None, **kwargs):
        payload_text = (json or {}).get("text", "")
        if payload_text.startswith("fail"):
            return _FakeResponse(status_code=503, text="Service Unavailable", _json={})
        return _FakeResponse(
            status_code=200,
            text="OK",
            _json={
                "translated_text": payload_text,
                "estimated_cost_usd": 0.001,
                "token_count": 100,
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post, raising=True)

    calls = {"judge": 0}

    def fake_evaluate(self, **kwargs):
        calls["judge"] += 1
        return JudgeResult(
            score=8.0,
            accuracy=8.0,
            fluency=8.0,
            completeness=8.0,
            reasoning="ok",
            issues=[],
            anomaly=False,
        )

    monkeypatch.setattr(LLMJudgeEvaluator, "evaluate", fake_evaluate, raising=True)

    from agents import mcp_client as _mcp_client

    monkeypatch.setattr(
        _mcp_client.MCPStorageClient,
        "save_eval_result",
        lambda *args, **kwargs: {"result_id": "res-partial", "timestamp": time.time()},
        raising=True,
    )

    state = {
        "run_id": "run-partial",
        "version_id": "v1",
        "test_suite_path": str(suite_path),
        "target_app_url": "http://fake-target",
        "errors": [],
    }

    test_cases = load_test_suite(state)["test_cases"]
    run_out = run_test_cases({**state, "test_cases": test_cases})

    eval_out = evaluate_outputs({**state, "test_results": run_out["test_results"]})
    agg_out = aggregate_results(
        {
            **state,
            "judge_results": eval_out["judge_results"],
            "test_results": run_out["test_results"],
            "errors": [],
        }
    )

    # Judge should be called only for completed cases.
    assert calls["judge"] == 3
    assert agg_out["quality_score"]["is_valid"] is True
    assert agg_out["quality_score"]["metadata"]["completed_test_cases"] == 3


def test_judge_api_error_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_CONFIG", "configs/local.json")
    monkeypatch.setenv("MCP_ALLOW_FALLBACK", "1")
    monkeypatch.setenv("STORAGE_DATA_DIR", str(tmp_path / "storage"))

    cases = [
        {
            "id": f"tc-{i}",
            "category": "simple_sentence",
            "source_lang": "en",
            "target_lang": "vi",
            "input": f"ok-{i}",
            "expected_output": f"expected-{i}",
        }
        for i in range(4)
    ]
    suite_path = _write_suite(tmp_path, cases)

    async def fake_post(self, url, json=None, **kwargs):
        payload_text = (json or {}).get("text", "")
        return _FakeResponse(
            status_code=200,
            text="OK",
            _json={
                "translated_text": payload_text,
                "estimated_cost_usd": 0.001,
                "token_count": 100,
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post, raising=True)

    def fake_evaluate(self, **kwargs):
        raise RuntimeError("judge failed")

    monkeypatch.setattr(LLMJudgeEvaluator, "evaluate", fake_evaluate, raising=True)

    from agents import mcp_client as _mcp_client

    monkeypatch.setattr(
        _mcp_client.MCPStorageClient,
        "save_eval_result",
        lambda *args, **kwargs: {"result_id": "res-judgeerr", "timestamp": time.time()},
        raising=True,
    )

    state = {
        "run_id": "run-judgeerr",
        "version_id": "v1",
        "test_suite_path": str(suite_path),
        "target_app_url": "http://fake-target",
        "errors": [],
    }

    test_cases = load_test_suite(state)["test_cases"]
    run_out = run_test_cases({**state, "test_cases": test_cases})
    eval_out = evaluate_outputs({**state, "test_results": run_out["test_results"]})
    agg_out = aggregate_results(
        {
            **state,
            "judge_results": eval_out["judge_results"],
            "test_results": run_out["test_results"],
            "errors": [],
        }
    )

    assert agg_out["quality_score"]["quality_score"] == 0.0
    assert agg_out["quality_score"]["is_valid"] is False


def test_empty_test_suite(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_CONFIG", "configs/local.json")
    monkeypatch.setenv("MCP_ALLOW_FALLBACK", "1")

    suite_path = _write_suite(tmp_path, [])

    state = {
        "run_id": "run-empty",
        "version_id": "v1",
        "test_suite_path": str(suite_path),
        "target_app_url": "http://fake-target",
        "errors": [],
    }

    load_out = load_test_suite(state)
    assert load_out["test_cases"] == []

    run_out = run_test_cases({**state, "test_cases": []})
    assert run_out["test_results"] == []

    eval_out = evaluate_outputs({**state, "test_results": []})
    assert eval_out["judge_results"] == []

    agg_out = aggregate_results(
        {
            **state,
            "judge_results": [],
            "test_results": [],
            "errors": [],
        }
    )
    assert agg_out["quality_score"]["quality_score"] == 0.0


def test_test_suite_not_found_returns_error(tmp_path):
    state = {
        "run_id": "run-missing",
        "version_id": "v1",
        "test_suite_path": str(tmp_path / "does-not-exist.json"),
        "target_app_url": "http://fake-target",
        "errors": [],
    }

    load_out = load_test_suite(state)
    assert load_out.get("status") == "error"
    assert len(load_out.get("errors", [])) > 0

