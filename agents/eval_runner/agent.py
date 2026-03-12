"""
Eval Runner Agent — LangGraph StateGraph that runs evaluation against the target app.

State Graph nodes:
    1. load_test_suite  — read test cases from JSON file or MCP Storage
    2. run_test_cases   — send inputs to target app, collect outputs + latency
    3. evaluate_outputs — use LLM-as-judge (Gemini Flash) to score each output
    4. aggregate_results — compute Quality Score via QualityScoreCalculator
    5. save_results     — persist eval results via MCP Storage

The agent calls:
    - Target app via HTTP (httpx)
    - MCP Storage tools via MCP client (for loading test suites / saving results)
    - Gemini Flash API via LLMJudgeEvaluator (for LLM-as-judge)

Edge cases handled:
    - Target app timeout → mark test case as FAILED (score=0)
    - LLM API error → retry up to 3 times, then mark as SKIPPED
    - Partial failures → continue with remaining test cases
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project root
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _atomic_write(path: Path, text: str) -> None:
    """Write *text* to *path* atomically (tmp file + os.replace)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# State schema for LangGraph
# ---------------------------------------------------------------------------


class EvalRunnerState(TypedDict, total=False):
    """State passed between LangGraph nodes."""
    # Input
    run_id: str
    version_id: str
    test_suite_path: str
    target_app_url: str
    # After load_test_suite
    test_cases: list[dict[str, Any]]
    # After run_test_cases
    test_results: list[dict[str, Any]]
    # After evaluate_outputs
    judge_results: list[dict[str, Any]]
    # After aggregate_results
    quality_score: dict[str, Any]
    # After save_results
    result_id: str
    status: str
    errors: list[str]


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


def load_test_suite(state: EvalRunnerState) -> dict[str, Any]:
    """
    Node 1: Load test cases from JSON file via MCP client.

    Uses MCPStorageClient which reads eval-datasets/*.json file.
    """
    from agents.mcp_client import MCPStorageClient

    test_suite_path = state.get("test_suite_path", "")
    if not test_suite_path:
        test_suite_path = str(_PROJECT_ROOT / "eval-datasets" / "baseline_v1.json")

    errors = list(state.get("errors", []))

    try:
        client = MCPStorageClient()
        test_cases = client.load_test_cases(test_suite_path)
        logger.info("Loaded %d test cases via MCP client", len(test_cases))
        return {"test_cases": test_cases}
    except FileNotFoundError as exc:
        errors.append(f"Test suite not found: {exc}")
        logger.error("Test suite not found: %s", exc)
        return {"test_cases": [], "errors": errors, "status": "error"}
    except Exception as exc:
        errors.append(f"Failed to load test suite: {exc}")
        logger.error("Failed to load test suite: %s", exc)
        return {"test_cases": [], "errors": errors, "status": "error"}


def run_test_cases(state: EvalRunnerState) -> dict[str, Any]:
    """
    Node 2: Send each test case input to the target app and collect outputs.

    Calls POST /translate on the target app for each test case.
    Uses async concurrency (semaphore-bounded) for performance.
    Retries up to 3 times per test case on failure.
    Records: actual_output, latency_ms, cost estimate, status.
    """
    test_cases = state.get("test_cases", [])
    target_url = state.get("target_app_url", "http://localhost:9001")
    errors = list(state.get("errors", []))

    if not test_cases:
        return {"test_results": [], "errors": errors}

    translate_url = f"{target_url.rstrip('/')}/translate"
    max_retries = 3
    max_concurrent = 10  # bound concurrent requests to avoid overwhelming target

    async def _run_single(
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        i: int,
        tc: dict[str, Any],
        local_errors: list[str],
    ) -> dict[str, Any] | None:
        """Run a single test case with retry logic."""
        tc_id = tc.get("id", f"case-{i+1}")
        # Use target_lang from test case; fall back to test suite metadata, not hardcode
        resolved_target_lang = tc.get("target_lang", "")
        if not resolved_target_lang:
            # Try test suite level metadata, then config, then truly default
            resolved_target_lang = state.get("default_target_lang", "en")

        payload = {
            "text": tc["input"],
            "source_lang": tc.get("source_lang", "vi"),
            "target_lang": resolved_target_lang,
        }

        last_error = None
        async with semaphore:
            for attempt in range(1, max_retries + 1):
                start_time = time.perf_counter()
                try:
                    resp = await client.post(translate_url, json=payload)
                    elapsed_ms = (time.perf_counter() - start_time) * 1000

                    if resp.status_code == 200:
                        data = resp.json()
                        return {
                            "test_case_id": tc_id,
                            "input": tc["input"],
                            "expected_output": tc.get("expected_output", ""),
                            "actual_output": data.get("translated_text", ""),
                            "source_lang": tc.get("source_lang", "vi"),
                            "target_lang": resolved_target_lang,
                            "latency_ms": round(elapsed_ms, 2),
                            "estimated_cost_usd": data.get("estimated_cost_usd", 0.0),
                            "token_count": data.get("token_count", 0),
                            "status": "completed",
                            "attempts": attempt,
                        }
                    else:
                        last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                        if attempt < max_retries:
                            logger.warning(
                                "Test case %s attempt %d/%d failed: %s — retrying",
                                tc_id, attempt, max_retries, last_error,
                            )
                            await asyncio.sleep(0.5 * attempt)

                except httpx.TimeoutException:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    last_error = f"timeout after {elapsed_ms:.0f}ms"
                    if attempt < max_retries:
                        logger.warning(
                            "Test case %s attempt %d/%d: timeout — retrying",
                            tc_id, attempt, max_retries,
                        )
                        await asyncio.sleep(0.5 * attempt)

                except Exception as exc:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    last_error = str(exc)
                    if attempt < max_retries:
                        logger.warning(
                            "Test case %s attempt %d/%d: %s — retrying",
                            tc_id, attempt, max_retries, exc,
                        )
                        await asyncio.sleep(0.5 * attempt)

            # All retries exhausted
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            # Determine status based on error type
            status = "failed"
            if last_error and "timeout" in last_error.lower():
                status = "timeout"
            elif last_error and "Connection" in last_error:
                status = "error"

            local_errors.append(
                f"Test case {tc_id}: {last_error} (after {max_retries} attempts)"
            )
            return {
                "test_case_id": tc_id,
                "input": tc["input"],
                "expected_output": tc.get("expected_output", ""),
                "actual_output": "",
                "source_lang": tc.get("source_lang", "vi"),
                "target_lang": resolved_target_lang,
                "latency_ms": round(elapsed_ms, 2),
                "estimated_cost_usd": 0.0,
                "status": status,
                "error": last_error,
                "attempts": max_retries,
            }

    async def _run_all() -> tuple[list[dict[str, Any]], list[str]]:
        """Run all test cases concurrently with bounded semaphore."""
        sem = asyncio.Semaphore(max_concurrent)
        timeout = httpx.Timeout(30.0, connect=10.0)
        local_errors: list[str] = []

        async with httpx.AsyncClient(timeout=timeout) as client:
            tasks = [
                _run_single(client, sem, i, tc, local_errors)
                for i, tc in enumerate(test_cases)
            ]
            results = await asyncio.gather(*tasks)

        return [r for r in results if r is not None], local_errors

    # Run the async event loop from sync context
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already in an async context — use nest_asyncio or thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            test_results, async_errors = pool.submit(
                lambda: asyncio.run(_run_all())
            ).result()
    else:
        test_results, async_errors = asyncio.run(_run_all())

    errors.extend(async_errors)

    completed = sum(1 for r in test_results if r["status"] == "completed")
    logger.info(
        "Test execution complete: %d/%d succeeded",
        completed,
        len(test_results),
    )
    return {"test_results": test_results, "errors": errors}


def evaluate_outputs(state: EvalRunnerState) -> dict[str, Any]:
    """
    Node 3: Use LLM-as-judge (Gemini Flash) to score each test case output.

    Only evaluates test cases with status="completed" (actual_output available).
    Skipped/failed test cases get score=0.
    """
    from .evaluator import LLMJudgeEvaluator

    test_results = state.get("test_results", [])
    errors = list(state.get("errors", []))

    if not test_results:
        return {"judge_results": [], "errors": errors}

    # Initialize judge from config
    thresholds_path = _PROJECT_ROOT / "configs" / "thresholds.json"
    api_key = os.environ.get("GEMINI_API_KEY", "")
    judge = LLMJudgeEvaluator.from_config(
        thresholds_path=thresholds_path,
        api_key=api_key,
    )

    # Single source of truth for pass_threshold: use QualityScoreCalculator
    from .quality_score import QualityScoreCalculator
    calculator = QualityScoreCalculator.from_config_file(thresholds_path)
    pass_threshold = calculator._pass_threshold

    judge_results: list[dict[str, Any]] = []

    for i, tr in enumerate(test_results):
        tc_id = tr["test_case_id"]

        if tr["status"] != "completed" or not tr.get("actual_output"):
            # Skip evaluation for failed/timeout test cases
            judge_results.append({
                "test_case_id": tc_id,
                "score": 0.0,
                "accuracy": 0.0,
                "fluency": 0.0,
                "completeness": 0.0,
                "reasoning": f"Test case {tr['status']} — not evaluated",
                "issues": [tr["status"]],
                "passed": False,
                "skipped": True,
            })
            continue

        logger.info(
            "Evaluating test case %d/%d: %s",
            i + 1,
            len(test_results),
            tc_id,
        )

        try:
            result = judge.evaluate(
                input_text=tr["input"],
                expected_output=tr["expected_output"],
                actual_output=tr["actual_output"],
                source_lang=tr.get("source_lang", "vi"),
                target_lang=tr.get("target_lang", "en"),
                run_id=state.get("run_id", ""),
                test_case_id=tc_id,
            )
            judge_results.append({
                "test_case_id": tc_id,
                **result.to_dict(),
                "passed": result.score >= pass_threshold,
                "skipped": False,
            })
        except Exception as exc:
            errors.append(f"Judge error for {tc_id}: {exc}")
            logger.error("Judge evaluation failed for %s: %s", tc_id, exc)
            judge_results.append({
                "test_case_id": tc_id,
                "score": 0.0,
                "accuracy": 0.0,
                "fluency": 0.0,
                "completeness": 0.0,
                "reasoning": f"Judge error: {exc}",
                "issues": ["judge_error"],
                "passed": False,
                "skipped": True,
            })

    passed = sum(1 for r in judge_results if r["passed"])
    logger.info(
        "Evaluation complete: %d/%d passed (score ≥ %.1f)",
        passed,
        len(judge_results),
        pass_threshold,
    )
    return {"judge_results": judge_results, "errors": errors}


def aggregate_results(state: EvalRunnerState) -> dict[str, Any]:
    """
    Node 4: Compute composite Quality Score from judge results + latency + cost.
    """
    from .quality_score import QualityScoreCalculator

    judge_results = state.get("judge_results", [])
    test_results = state.get("test_results", [])
    run_id = state.get("run_id", "")
    version_id = state.get("version_id", "")
    errors = list(state.get("errors", []))

    if not judge_results:
        return {
            "quality_score": {"quality_score": 0.0, "breakdown": {}, "metadata": {}},
            "errors": errors,
        }

    # Build lookup for latency/cost from test_results
    tr_map = {tr["test_case_id"]: tr for tr in test_results}

    # Collect scores, latencies, costs (only for non-skipped cases)
    test_case_scores: list[float] = []
    latencies_ms: list[float] = []
    costs_usd: list[float] = []
    skipped = 0

    for jr in judge_results:
        if jr.get("skipped", False):
            skipped += 1
            continue
        test_case_scores.append(jr["score"])
        tc_id = jr["test_case_id"]
        tr = tr_map.get(tc_id, {})
        latencies_ms.append(tr.get("latency_ms", 0.0))
        costs_usd.append(tr.get("estimated_cost_usd", 0.0))

    # Calculate quality score
    thresholds_path = _PROJECT_ROOT / "configs" / "thresholds.json"
    calculator = QualityScoreCalculator.from_config_file(thresholds_path)

    qs_result = calculator.calculate(
        test_case_scores=test_case_scores,
        latencies_ms=latencies_ms,
        costs_usd=costs_usd,
        total_cases=len(judge_results),
        skipped_cases=skipped,
        version_id=version_id,
        run_id=run_id,
    )

    quality_score_dict = qs_result.to_dict()
    if qs_result.warnings:
        errors.extend(qs_result.warnings)

    logger.info("Quality Score: %.3f", qs_result.quality_score)
    return {"quality_score": quality_score_dict, "errors": errors}


def save_results(state: EvalRunnerState) -> dict[str, Any]:
    """
    Node 5: Save evaluation results via MCP Storage client.

    Uses MCPStorageClient which tries MCP server first,
    then falls back to direct file write.
    """
    from agents.mcp_client import MCPStorageClient

    run_id = state.get("run_id", str(uuid.uuid4()))
    version_id = state.get("version_id", "")
    quality_score = state.get("quality_score", {})
    judge_results = state.get("judge_results", [])
    test_results = state.get("test_results", [])
    errors = list(state.get("errors", []))

    # Build detail records (merge judge + test results)
    details: list[dict[str, Any]] = []
    tr_map = {tr["test_case_id"]: tr for tr in test_results}

    for jr in judge_results:
        tc_id = jr["test_case_id"]
        tr = tr_map.get(tc_id, {})
        details.append({
            "test_case_id": tc_id,
            "input": tr.get("input", ""),
            "expected_output": tr.get("expected_output", ""),
            "actual_output": tr.get("actual_output", ""),
            "score": jr.get("score", 0.0),
            "accuracy": jr.get("accuracy", 0.0),
            "fluency": jr.get("fluency", 0.0),
            "completeness": jr.get("completeness", 0.0),
            "reasoning": jr.get("reasoning", ""),
            "issues": jr.get("issues", []),
            "passed": jr.get("passed", False),
            "skipped": jr.get("skipped", False),
            "latency_ms": tr.get("latency_ms", 0.0),
            "estimated_cost_usd": tr.get("estimated_cost_usd", 0.0),
            "status": tr.get("status", "unknown"),
        })

    # Save via MCP client (tries server first, falls back to direct write)
    try:
        client = MCPStorageClient()
        scores_dict = {
            "quality_score": quality_score.get("quality_score", 0.0),
            "breakdown": quality_score.get("breakdown", {}),
        }
        save_result = client.save_eval_result(
            run_id=run_id,
            version_id=version_id,
            scores=scores_dict,
            details=details,
        )
        result_id = save_result.get("result_id", "")

        logger.info(
            "Eval results saved: run_id=%s, result_id=%s, score=%.3f",
            run_id,
            result_id,
            quality_score.get("quality_score", 0.0),
        )
        return {
            "result_id": result_id,
            "status": "completed",
            "errors": errors,
        }
    except Exception as exc:
        # Last resort: write directly to .local-data
        logger.warning("MCP client save failed, using direct file write: %s", exc)
        data_dir = Path(
            os.environ.get("STORAGE_DATA_DIR", str(_PROJECT_ROOT / ".local-data"))
        )
        run_dir = data_dir / "eval-results" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        result_id = str(uuid.uuid4())
        record = {
            "result_id": result_id,
            "run_id": run_id,
            "version_id": version_id,
            "quality_score": quality_score.get("quality_score", 0.0),
            "score_breakdown": quality_score.get("breakdown", {}),
            "total_test_cases": len(details),
            "passed_test_cases": sum(1 for d in details if d.get("passed")),
            "status": "completed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": details,
            "errors": errors,
        }

        result_path = run_dir / "result.json"
        _atomic_write(
            result_path,
            json.dumps(record, indent=2, ensure_ascii=False),
        )

        return {
            "result_id": result_id,
            "status": "completed",
            "errors": errors,
        }


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_eval_runner_graph():
    """
    Build the Eval Runner LangGraph StateGraph.

    Returns a compiled graph that can be invoked with:
        result = graph.invoke({
            "run_id": "...",
            "version_id": "...",
            "test_suite_path": "eval-datasets/baseline_v1.json",
            "target_app_url": "http://localhost:9000",
        })
    """
    from langgraph.graph import END, StateGraph

    graph = StateGraph(EvalRunnerState)

    # Add nodes
    graph.add_node("load_test_suite", load_test_suite)
    graph.add_node("run_test_cases", run_test_cases)
    graph.add_node("evaluate_outputs", evaluate_outputs)
    graph.add_node("aggregate_results", aggregate_results)
    graph.add_node("save_results", save_results)

    # Define edges — linear pipeline with early exit on error
    graph.set_entry_point("load_test_suite")

    def should_continue_after_load(state: EvalRunnerState) -> str:
        if state.get("status") == "error" or not state.get("test_cases"):
            return "save_results"  # save error state
        return "run_test_cases"

    graph.add_conditional_edges(
        "load_test_suite",
        should_continue_after_load,
        {"run_test_cases": "run_test_cases", "save_results": "save_results"},
    )

    def should_continue_after_run(state: EvalRunnerState) -> str:
        """Skip evaluation if all test cases failed (app down scenario)."""
        results = state.get("test_results", [])
        completed = sum(1 for r in results if r.get("status") == "completed")
        if completed == 0:
            return "aggregate_results"  # skip judge, go straight to scoring
        return "evaluate_outputs"

    graph.add_conditional_edges(
        "run_test_cases",
        should_continue_after_run,
        {"evaluate_outputs": "evaluate_outputs", "aggregate_results": "aggregate_results"},
    )
    graph.add_edge("evaluate_outputs", "aggregate_results")
    graph.add_edge("aggregate_results", "save_results")
    graph.add_edge("save_results", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------

# Module-level compiled graph — built once on first call.
_EVAL_RUNNER_GRAPH: Any = None


def run_eval(
    version_id: str = "",
    test_suite_path: str = "",
    target_app_url: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """
    Run a full eval pipeline synchronously.

    Args:
        version_id: The version being evaluated.
        test_suite_path: Path to test suite JSON file.
        target_app_url: URL of the target app (e.g., http://localhost:9000).
        run_id: Optional run ID (auto-generated if empty).

    Returns:
        Final state dict with quality_score, result_id, status.
    """
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_PROJECT_ROOT / ".env")

    # Configure LangSmith tracing
    from agents.tracing import configure_tracing, get_graph_config
    configure_tracing()

    if not run_id:
        run_id = str(uuid.uuid4())
    if not target_app_url:
        # Load from config
        config_path = os.environ.get(
            "APP_CONFIG", str(_PROJECT_ROOT / "configs" / "local.json")
        )
        try:
            config = json.loads(Path(config_path).read_text(encoding="utf-8"))
            target_app_url = config.get("target_app", {}).get(
                "staging_url", "http://localhost:9001"
            )
        except Exception:
            target_app_url = "http://localhost:9001"

    global _EVAL_RUNNER_GRAPH
    if _EVAL_RUNNER_GRAPH is None:
        _EVAL_RUNNER_GRAPH = build_eval_runner_graph()

    initial_state: EvalRunnerState = {
        "run_id": run_id,
        "version_id": version_id,
        "test_suite_path": test_suite_path,
        "target_app_url": target_app_url,
        "errors": [],
    }

    # Build LangSmith tracing config
    trace_config = get_graph_config(
        run_name=f"eval-runner-{run_id[:8]}",
        tags=["eval-runner", f"version-{version_id}"],
        metadata={
            "run_id": run_id,
            "version_id": version_id,
            "target_app_url": target_app_url,
        },
    )

    logger.info(
        "Starting eval run: run_id=%s, version=%s, target=%s",
        run_id,
        version_id,
        target_app_url,
    )
    start = time.perf_counter()
    result = _EVAL_RUNNER_GRAPH.invoke(initial_state, config=trace_config)
    elapsed = time.perf_counter() - start

    logger.info(
        "Eval run completed in %.1fs: score=%.3f, status=%s",
        elapsed,
        result.get("quality_score", {}).get("quality_score", 0.0),
        result.get("status", "unknown"),
    )
    return result


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(_PROJECT_ROOT / ".env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    parser = argparse.ArgumentParser(description="Run eval pipeline")
    parser.add_argument("--version-id", default="", help="Version ID to evaluate")
    parser.add_argument(
        "--test-suite",
        default="",
        help="Path to test suite JSON file",
    )
    parser.add_argument(
        "--target-url",
        default="",
        help="Target app URL (default: from config)",
    )
    parser.add_argument("--run-id", default="", help="Custom run ID")
    args = parser.parse_args()

    result = run_eval(
        version_id=args.version_id,
        test_suite_path=args.test_suite,
        target_app_url=args.target_url,
        run_id=args.run_id,
    )

    print("\n" + "=" * 60)
    print("EVAL RUN RESULTS")
    print("=" * 60)
    qs = result.get("quality_score", {})
    print(f"  Quality Score: {qs.get('quality_score', 0):.3f}")
    breakdown = qs.get("breakdown", {})
    for dim, info in breakdown.items():
        print(f"  {dim}: {info.get('score', 0):.2f} (weight: {info.get('weight', 0)})")
    print(f"  Status: {result.get('status', 'unknown')}")
    print(f"  Result ID: {result.get('result_id', 'N/A')}")
    if result.get("errors"):
        print(f"  Warnings: {len(result['errors'])}")
        for err in result["errors"][:5]:
            print(f"    - {err}")
    print("=" * 60)
