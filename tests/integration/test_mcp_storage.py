from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agents.mcp_client import MCPStorageClient


def _write_suite(tmp_path: Path) -> Path:
    p = tmp_path / "suite.json"
    p.write_text(
        json.dumps(
            [
                {
                    "id": "tc-1",
                    "category": "simple_sentence",
                    "source_lang": "en",
                    "target_lang": "vi",
                    "input": "hello",
                    "expected_output": "xin chao",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return p


def test_save_and_load_eval_result(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_CONFIG", "configs/local.json")
    monkeypatch.setenv("MCP_ALLOW_FALLBACK", "1")
    monkeypatch.setenv("STORAGE_DATA_DIR", str(tmp_path / "storage"))

    client = MCPStorageClient()

    run_id = "run-store-1"
    version_id = "v-store-1"
    scores = {"quality_score": 8.25, "breakdown": {"task_completion": {"score": 10, "weight": 0.35, "raw_value": 100}}}
    details = [
        {
            "test_case_id": "tc-1",
            "passed": True,
            "skipped": False,
            "latency_ms": 12.0,
            "estimated_cost_usd": 0.001,
        }
    ]

    save = client.save_eval_result(run_id=run_id, version_id=version_id, scores=scores, details=details)
    assert save["result_id"]

    results = client.get_eval_results(run_id=run_id)
    assert len(results) >= 1
    assert results[0]["run_id"] == run_id
    assert results[0]["version_id"] == version_id


def test_fallback_when_mcp_down(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_CONFIG", "configs/local.json")
    monkeypatch.setenv("MCP_ALLOW_FALLBACK", "1")
    monkeypatch.setenv("STORAGE_DATA_DIR", str(tmp_path / "storage"))

    client = MCPStorageClient()

    run_id = "run-store-2"
    version_id = "v-store-2"
    scores = {"quality_score": 1.0, "breakdown": {}}
    details = [{"test_case_id": "tc-1", "passed": False, "skipped": True}]

    save = client.save_eval_result(run_id=run_id, version_id=version_id, scores=scores, details=details)
    assert save["result_id"]

    results = client.get_eval_results(version_id=version_id)
    assert len(results) >= 1


def test_load_test_cases_from_file(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_CONFIG", "configs/local.json")
    monkeypatch.setenv("MCP_ALLOW_FALLBACK", "1")

    client = MCPStorageClient()
    suite_path = _write_suite(tmp_path)
    cases = client.load_test_cases(str(suite_path))
    assert len(cases) == 1
    assert cases[0]["id"] == "tc-1"


def test_concurrent_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_CONFIG", "configs/local.json")
    monkeypatch.setenv("MCP_ALLOW_FALLBACK", "1")
    monkeypatch.setenv("STORAGE_DATA_DIR", str(tmp_path / "storage"))

    client = MCPStorageClient()
    version_id = "v-store-concurrent"

    def _save(i: int):
        run_id = f"run-store-concurrent-{i}"
        scores = {"quality_score": float(i), "breakdown": {}}
        details = [{"test_case_id": "tc-1", "passed": i % 2 == 0, "skipped": False}]
        client.save_eval_result(run_id=run_id, version_id=version_id, scores=scores, details=details)

    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(_save, range(5)))

    results = client.get_eval_results(version_id=version_id)
    assert len(results) == 5

