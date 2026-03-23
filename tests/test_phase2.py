"""
Phase 2 — Eval Pipeline Unit & Integration Tests.

Tests all Phase 2 components:
    - Quality Score Calculator (P2-5, P2-6)
    - LLM-as-Judge Evaluator (P2-4) — unit tests with mocked LLM
    - Eval Runner Agent (P2-1, P2-2, P2-3) — state graph structure
    - Eval Orchestrator Agent (P2-7, P2-8) — state graph structure + locking

Run:
    python tests/test_phase2.py

Expected: all tests pass without API keys or running servers.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Resolve project root
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "agents"))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "eval_runner"))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "orchestrator"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "storage"))

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

_pass_count = 0
_fail_count = 0


def test(name: str, condition: bool, detail: str = "") -> None:
    global _pass_count, _fail_count
    if condition:
        _pass_count += 1
        print(f"  \u2705 {name}")
    else:
        _fail_count += 1
        msg = f"  \u274c {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


# ============================================================================
# TEST SECTION 1: Quality Score Calculator — Normalization Formulas
# ============================================================================

print("=" * 60)
print("Phase 2 — Eval Pipeline Tests")
print("=" * 60)

print("\n[1/18] Quality Score — Normalization Formulas")

from agents.eval_runner.quality_score import QualityScoreCalculator, QualityScoreResult

# Task Completion normalization: score = raw_percentage / 10
test(
    "normalize_task_completion(86%) = 8.6",
    abs(QualityScoreCalculator.normalize_task_completion(86.0) - 8.6) < 0.01,
)
test(
    "normalize_task_completion(100%) = 10.0",
    abs(QualityScoreCalculator.normalize_task_completion(100.0) - 10.0) < 0.01,
)
test(
    "normalize_task_completion(0%) = 0.0",
    abs(QualityScoreCalculator.normalize_task_completion(0.0) - 0.0) < 0.01,
)

# Output Quality: direct use (0-10)
test(
    "normalize_output_quality(7.8) = 7.8",
    abs(QualityScoreCalculator.normalize_output_quality(7.8) - 7.8) < 0.01,
)
test(
    "normalize_output_quality clamped to 10",
    abs(QualityScoreCalculator.normalize_output_quality(15.0) - 10.0) < 0.01,
)

# Latency: score = 10 - min(ms/1000, 10)
test(
    "normalize_latency(1800ms) = 8.2",
    abs(QualityScoreCalculator.normalize_latency(1800.0) - 8.2) < 0.01,
)
test(
    "normalize_latency(0ms) = 10.0",
    abs(QualityScoreCalculator.normalize_latency(0.0) - 10.0) < 0.01,
)
test(
    "normalize_latency(15000ms) = 0.0",
    abs(QualityScoreCalculator.normalize_latency(15000.0) - 0.0) < 0.01,
)

# Cost: score = 10 - min(cost * 100, 10)
test(
    "normalize_cost($0.002) = 9.8",
    abs(QualityScoreCalculator.normalize_cost(0.002) - 9.8) < 0.01,
)
test(
    "normalize_cost($0) = 10.0",
    abs(QualityScoreCalculator.normalize_cost(0.0) - 10.0) < 0.01,
)
test(
    "normalize_cost($0.15) = 0.0 (clamped)",
    abs(QualityScoreCalculator.normalize_cost(0.15) - 0.0) < 0.01,
)


# ============================================================================
# TEST SECTION 2: Quality Score Calculator — Full Calculation
# ============================================================================

print("\n[2/18] Quality Score — Full Calculation (Spec Case A)")

calc = QualityScoreCalculator()

# Case A from quality_score_spec.md:
# 50 cases, 43 passed (86%), avg judge=7.8, avg latency=1800ms, avg cost=$0.002
# Expected: 8.360
scores_a = [8.0] * 43 + [4.0] * 7  # 43 pass (≥6.0), 7 fail
latencies_a = [1800.0] * 50
costs_a = [0.002] * 50

result_a = calc.calculate(
    test_case_scores=scores_a,
    latencies_ms=latencies_a,
    costs_usd=costs_a,
    version_id="test-v1",
    run_id="test-run-1",
)

test(
    "Quality Score is a QualityScoreResult",
    isinstance(result_a, QualityScoreResult),
)
test(
    "Case A quality_score ≈ 8.36 (within ±0.5)",
    abs(result_a.quality_score - 8.36) < 0.5,
    f"got {result_a.quality_score:.3f}",
)
test(
    "breakdown has 4 dimensions",
    len(result_a.breakdown) == 4,
)
test(
    "breakdown keys correct",
    set(result_a.breakdown.keys())
    == {"task_completion", "output_quality", "latency", "cost_efficiency"},
)
test(
    "metadata contains version_id",
    result_a.metadata.get("version_id") == "test-v1",
)
test(
    "metadata contains run_id",
    result_a.metadata.get("run_id") == "test-run-1",
)

# ============================================================================
# TEST SECTION 3: Quality Score — Case B (Regression)
# ============================================================================

print("\n[3/18] Quality Score — Regression Case (Spec Case B)")

# Case B: 50 cases, 28 passed (56%), avg=4.9, 2200ms, $0.002
scores_b = [7.0] * 28 + [3.0] * 22  # 28 pass, 22 fail
latencies_b = [2200.0] * 50
costs_b = [0.002] * 50

result_b = calc.calculate(test_case_scores=scores_b, latencies_ms=latencies_b, costs_usd=costs_b)

test(
    "Case B quality_score < Case A (regression)",
    result_b.quality_score < result_a.quality_score,
    f"B={result_b.quality_score:.3f} vs A={result_a.quality_score:.3f}",
)
test(
    "Case B task_completion score lower than Case A",
    result_b.breakdown["task_completion"]["score"]
    < result_a.breakdown["task_completion"]["score"],
)

# ============================================================================
# TEST SECTION 4: Quality Score — Edge Cases
# ============================================================================

print("\n[4/18] Quality Score — Edge Cases")

# Empty test cases — all dimensions should be 0 when no data
# (Fix #1: no data → penalize, not reward. App down must not inflate score)
result_empty = calc.calculate(
    test_case_scores=[], latencies_ms=[], costs_usd=[]
)
test(
    "Empty test cases → task_completion and output_quality = 0",
    result_empty.breakdown["task_completion"]["score"] < 0.01
    and result_empty.breakdown["output_quality"]["score"] < 0.01,
)
test(
    "Empty test cases → latency score = 0 (no data, not 10)",
    result_empty.breakdown["latency"]["score"] < 0.01,
)
test(
    "Empty test cases → cost_efficiency score = 0 (no data, not 10)",
    result_empty.breakdown["cost_efficiency"]["score"] < 0.01,
)
test(
    "Empty test cases → overall quality_score = 0.0 (app down)",
    result_empty.quality_score < 0.01,
)

# All perfect scores
result_perfect = calc.calculate(
    test_case_scores=[10.0] * 10,
    latencies_ms=[500.0] * 10,
    costs_usd=[0.001] * 10,
)
test(
    "Perfect scores → quality_score near 10",
    result_perfect.quality_score > 9.5,
    f"got {result_perfect.quality_score:.3f}",
)

# With skipped cases
result_skipped = calc.calculate(
    test_case_scores=[8.0] * 3,
    latencies_ms=[1000.0] * 3,
    costs_usd=[0.002] * 3,
    total_cases=10,
    skipped_cases=7,
)
test(
    "Skipped cases produce warning (< 50% completed)",
    len(result_skipped.warnings) > 0,
)

# to_dict serialization
d = result_a.to_dict()
test(
    "to_dict() returns dict with quality_score",
    isinstance(d, dict) and "quality_score" in d,
)
test(
    "to_dict() has breakdown",
    "breakdown" in d and len(d["breakdown"]) == 4,
)

# ============================================================================
# TEST SECTION 5: Quality Score — from_config_file
# ============================================================================

print("\n[5/18] Quality Score — Config File Loading")

thresholds_path = PROJECT_ROOT / "configs" / "thresholds.json"
test(
    "thresholds.json exists",
    thresholds_path.exists(),
)

calc_from_config = QualityScoreCalculator.from_config_file(thresholds_path)
test(
    "from_config_file creates calculator",
    isinstance(calc_from_config, QualityScoreCalculator),
)

# Test with valid config
config_data = json.loads(thresholds_path.read_text(encoding="utf-8"))
test(
    "Config has per_dimension_weights",
    "per_dimension_weights" in config_data,
)
test(
    "Weights sum to 1.0",
    abs(sum(config_data["per_dimension_weights"].values()) - 1.0) < 0.01,
)

# Test with nonexistent path (should use defaults)
calc_missing = QualityScoreCalculator.from_config_file("/nonexistent.json")
test(
    "Missing config falls back to defaults",
    isinstance(calc_missing, QualityScoreCalculator),
)

# Invalid weights should raise
try:
    QualityScoreCalculator(weights={"a": 0.5, "b": 0.1})
    test("Invalid weights raise ValueError", False)
except ValueError:
    test("Invalid weights raise ValueError", True)


# ============================================================================
# TEST SECTION 6: LLM-as-Judge — JSON Parsing
# ============================================================================

print("\n[6/18] LLM-as-Judge — Response Parsing & Validation")

from agents.eval_runner.evaluator import LLMJudgeEvaluator, JudgeResult

# Test JSON parsing
valid_json = json.dumps({
    "accuracy": 8.5,
    "fluency": 9.0,
    "completeness": 7.5,
    "score": 8.3,
    "reasoning": "Good translation",
    "issues": [],
})
parsed = LLMJudgeEvaluator._parse_json_response(valid_json)
test("Valid JSON parsed correctly", parsed is not None)
test("Parsed score = 8.3", parsed is not None and abs(parsed["score"] - 8.3) < 0.01)
test(
    "Parsed accuracy = 8.5",
    parsed is not None and abs(parsed["accuracy"] - 8.5) < 0.01,
)

# Test JSON in markdown code block
markdown_json = '```json\n{"accuracy": 7.0, "fluency": 8.0, "completeness": 6.0, "score": 7.0, "reasoning": "ok", "issues": []}\n```'
parsed_md = LLMJudgeEvaluator._parse_json_response(markdown_json)
test("JSON in markdown code block parsed", parsed_md is not None)

# Invalid JSON
test(
    "Invalid JSON returns None",
    LLMJudgeEvaluator._parse_json_response("not json") is None,
)

# Missing required fields
incomplete = json.dumps({"score": 8.0})
test(
    "Missing fields returns None",
    LLMJudgeEvaluator._parse_json_response(incomplete) is None,
)

# Score clamping
extreme = json.dumps({
    "accuracy": 15.0, "fluency": -3.0, "completeness": 8.0,
    "score": 12.0, "reasoning": "test", "issues": [],
})
parsed_extreme = LLMJudgeEvaluator._parse_json_response(extreme)
test(
    "Score > 10 clamped to 10",
    parsed_extreme is not None and parsed_extreme["score"] == 10.0,
)
test(
    "Score < 0 clamped to 0",
    parsed_extreme is not None and parsed_extreme["fluency"] == 0.0,
)

# JudgeResult dataclass
jr = JudgeResult(
    score=8.0, accuracy=8.5, fluency=9.0, completeness=7.0,
    reasoning="Good", issues=["minor issue"],
)
jr_dict = jr.to_dict()
test("JudgeResult.to_dict() has score", "score" in jr_dict)
test("JudgeResult.to_dict() has criteria", "accuracy" in jr_dict)


# ============================================================================
# TEST SECTION 7: LLM-as-Judge — Evaluator Config
# ============================================================================

print("\n[7/18] LLM-as-Judge — Configuration")

# from_config with thresholds
evaluator = LLMJudgeEvaluator.from_config(
    thresholds_path=thresholds_path,
    api_key="test-key",
)
test("Evaluator created from config", isinstance(evaluator, LLMJudgeEvaluator))
test("Evaluator temperature from config", evaluator._temperature == 0.0)
test("Evaluator passes from config", evaluator._num_passes == 2)
test(
    "Evaluator anomaly threshold from config",
    abs(evaluator._anomaly_threshold - 2.0) < 0.01,
)

# Direct construction
evaluator_custom = LLMJudgeEvaluator(
    api_key="test",
    model_name="gemini-2.5-flash",
    temperature=0.0,
    num_passes=3,
    anomaly_threshold=1.5,
)
test("Custom evaluator num_passes=3", evaluator_custom._num_passes == 3)
test(
    "Custom evaluator anomaly_threshold=1.5",
    abs(evaluator_custom._anomaly_threshold - 1.5) < 0.01,
)


# ============================================================================
# TEST SECTION 8: Eval Runner Agent — Graph Structure
# ============================================================================

print("\n[8/18] Eval Runner Agent — State Graph Structure")

from agents.eval_runner.agent import (
    EvalRunnerState,
    build_eval_runner_graph,
    load_test_suite,
    aggregate_results,
)

# Test load_test_suite node
baseline_path = str(PROJECT_ROOT / "eval-datasets" / "baseline_v1.json")
state_load: EvalRunnerState = {
    "test_suite_path": baseline_path,
    "errors": [],
}
load_result = load_test_suite(state_load)
test(
    "load_test_suite loads baseline_v1.json",
    len(load_result.get("test_cases", [])) >= 10,
    f"got {len(load_result.get('test_cases', []))} cases",
)

# Test load with missing file
state_missing: EvalRunnerState = {
    "test_suite_path": "/nonexistent/test.json",
    "errors": [],
}
missing_result = load_test_suite(state_missing)
test(
    "load_test_suite handles missing file",
    missing_result.get("status") == "error",
)
test(
    "Missing file produces error message",
    len(missing_result.get("errors", [])) > 0,
)

# Test aggregate_results node with mock data
mock_judge_results = [
    {"test_case_id": f"tc-{i}", "score": 8.0, "passed": True, "skipped": False}
    for i in range(8)
] + [
    {"test_case_id": f"tc-{i}", "score": 4.0, "passed": False, "skipped": False}
    for i in range(8, 10)
]
mock_test_results = [
    {"test_case_id": f"tc-{i}", "latency_ms": 1500.0, "estimated_cost_usd": 0.002}
    for i in range(10)
]

state_agg: EvalRunnerState = {
    "judge_results": mock_judge_results,
    "test_results": mock_test_results,
    "run_id": "test-run",
    "version_id": "test-v1",
    "errors": [],
}
agg_result = aggregate_results(state_agg)
test(
    "aggregate_results produces quality_score",
    "quality_score" in agg_result,
)
qs = agg_result["quality_score"]
test(
    "Quality score is a number > 0",
    isinstance(qs.get("quality_score"), (int, float)) and qs["quality_score"] > 0,
)
test(
    "Quality score breakdown present",
    "breakdown" in qs and len(qs["breakdown"]) == 4,
)

# Build graph and verify structure
graph = build_eval_runner_graph()
test("Eval runner graph compiles", graph is not None)

# Check the graph has the expected node names
graph_nodes = set()
if hasattr(graph, 'nodes'):
    graph_nodes = set(graph.nodes.keys())
elif hasattr(graph, 'get_graph'):
    g = graph.get_graph()
    graph_nodes = set(g.nodes.keys())

expected_nodes = {"load_test_suite", "run_test_cases", "evaluate_outputs", "aggregate_results", "save_results"}
# Graph may include __start__ and __end__ nodes
actual_agent_nodes = graph_nodes - {"__start__", "__end__"}
test(
    "Graph has all 5 eval runner nodes",
    expected_nodes.issubset(actual_agent_nodes),
    f"got {actual_agent_nodes}",
)


# ============================================================================
# TEST SECTION 9: Eval Orchestrator — Graph Structure & Locking
# ============================================================================

print("\n[9/18] Eval Orchestrator — Graph Structure & Locking")

from agents.orchestrator.agent import (
    OrchestratorState,
    build_orchestrator_graph,
    receive_trigger,
    parse_change,
    check_lock,
    _acquire_lock,
    _release_lock,
)

# Test receive_trigger
state_trigger: OrchestratorState = {
    "trigger_type": "manual",
}
trigger_result = receive_trigger(state_trigger)
test(
    "receive_trigger sets run_id",
    "run_id" in trigger_result and len(trigger_result["run_id"]) > 0,
)
test(
    "receive_trigger sets status=running",
    trigger_result.get("status") == "running",
)
test(
    "receive_trigger sets started_at",
    "started_at" in trigger_result,
)

# Test parse_change — manual
state_manual: OrchestratorState = {
    "trigger_type": "manual",
    "webhook_payload": {},
}
manual_result = parse_change(state_manual)
test(
    "Manual trigger → change_type=config",
    manual_result.get("change_type") == "config",
)

# Test parse_change — webhook with prompt change
state_webhook: OrchestratorState = {
    "trigger_type": "webhook",
    "webhook_payload": {
        "ref": "refs/heads/main",
        "after": "abc12345",
        "commits": [
            {
                "added": [],
                "modified": ["configs/prompt_template.json"],
                "removed": [],
            }
        ],
    },
}
webhook_result = parse_change(state_webhook)
test(
    "Webhook with prompt change → change_type=prompt",
    webhook_result.get("change_type") == "prompt",
)
test(
    "Webhook parses commit_sha",
    webhook_result.get("commit_sha") == "abc12345",
)

# Test parse_change — webhook with code change
state_code: OrchestratorState = {
    "trigger_type": "webhook",
    "webhook_payload": {
        "ref": "refs/heads/main",
        "after": "def67890",
        "commits": [
            {
                "added": [],
                "modified": ["target-app/translator.py"],
                "removed": [],
            }
        ],
    },
}
code_result = parse_change(state_code)
test(
    "Webhook with code change → change_type=code",
    code_result.get("change_type") == "code",
)

# Test parse_change — irrelevant files
state_irrelevant: OrchestratorState = {
    "trigger_type": "webhook",
    "webhook_payload": {
        "ref": "refs/heads/main",
        "after": "xyz000",
        "commits": [
            {
                "added": [],
                "modified": ["docs/readme.md"],
                "removed": [],
            }
        ],
    },
}
irrelevant_result = parse_change(state_irrelevant)
test(
    "Irrelevant file change → change_type=irrelevant",
    irrelevant_result.get("change_type") == "irrelevant",
)

# Test concurrent locking
_test_lock_dir = tempfile.mkdtemp(prefix="agentops-lock-test-")

# Patch the lock directory for testing
import agents.orchestrator.agent as orch_module
original_lock_dir = orch_module._LOCK_DIR
orch_module._LOCK_DIR = Path(_test_lock_dir)

test_run_id = "test-lock-" + str(uuid.uuid4())[:8]

# Acquire lock
acquired = _acquire_lock(test_run_id)
test("Lock acquired successfully", acquired)

# Try to acquire again — should fail
acquired_again = _acquire_lock("another-run")
test("Second lock acquire fails (lock held)", not acquired_again)

# Release lock
_release_lock(test_run_id)
lock_file = Path(_test_lock_dir) / "pipeline.lock"
test("Lock released (file removed)", not lock_file.exists())

# Acquire after release — should succeed
acquired_after = _acquire_lock("post-release-run")
test("Lock acquired after release", acquired_after)
_release_lock("post-release-run")

# Restore original lock dir
orch_module._LOCK_DIR = original_lock_dir
shutil.rmtree(_test_lock_dir, ignore_errors=True)

# Build orchestrator graph
orch_graph = build_orchestrator_graph()
test("Orchestrator graph compiles", orch_graph is not None)

orch_nodes = set()
if hasattr(orch_graph, 'nodes'):
    orch_nodes = set(orch_graph.nodes.keys())
elif hasattr(orch_graph, 'get_graph'):
    g = orch_graph.get_graph()
    orch_nodes = set(g.nodes.keys())

expected_orch_nodes = {
    "receive_trigger", "parse_change", "check_lock",
    "prepare_eval", "run_eval", "route_result",
}
actual_orch_nodes = orch_nodes - {"__start__", "__end__"}
test(
    "Orchestrator has all 6 nodes",
    expected_orch_nodes.issubset(actual_orch_nodes),
    f"got {actual_orch_nodes}",
)


# ============================================================================
# TEST SECTION 10: Integration — Configs & File Structure
# ============================================================================

print("\n[10/18] Integration — File Structure & Configs")

# Verify all Phase 2 files exist
phase2_files = [
    "agents/__init__.py",
    "agents/eval_runner/__init__.py",
    "agents/eval_runner/agent.py",
    "agents/eval_runner/evaluator.py",
    "agents/eval_runner/quality_score.py",
    "agents/orchestrator/__init__.py",
    "agents/orchestrator/agent.py",
]

for f in phase2_files:
    path = PROJECT_ROOT / f
    test(f"File exists: {f}", path.exists())

# Verify quality_score_spec.md exists and has key sections
spec_path = PROJECT_ROOT / "configs" / "quality_score_spec.md"
test("quality_score_spec.md exists", spec_path.exists())
if spec_path.exists():
    spec_content = spec_path.read_text(encoding="utf-8")
    test(
        "Spec has 4 dimensions documented",
        "Task Completion" in spec_content
        and "Output Quality" in spec_content
        and "Latency" in spec_content
        and "Cost Efficiency" in spec_content,
    )
    test(
        "Spec has LLM-as-Judge protocol",
        "LLM-as-Judge" in spec_content,
    )

# Verify thresholds.json has all required fields
thresholds = json.loads(thresholds_path.read_text(encoding="utf-8"))
required_threshold_keys = [
    "escalate_threshold",
    "rollback_threshold",
    "auto_promote_threshold",
    "per_dimension_weights",
    "test_case_pass_threshold",
    "min_test_cases_required",
    "judge_temperature",
    "judge_passes",
    "judge_anomaly_threshold",
    "judge_prompt_variant",
]
for key in required_threshold_keys:
    test(f"thresholds.json has '{key}'", key in thresholds)

# Verify eval dataset exists and has ≥ 10 cases
baseline = json.loads(
    (PROJECT_ROOT / "eval-datasets" / "baseline_v1.json").read_text(encoding="utf-8")
)
test(
    "baseline_v1.json has ≥ 10 test cases",
    len(baseline) >= 10,
    f"got {len(baseline)}",
)

# Verify each test case has required fields
required_tc_fields = {"id", "category", "input", "expected_output"}
for tc in baseline:
    has_fields = required_tc_fields.issubset(tc.keys())
    if not has_fields:
        test(
            f"Test case {tc.get('id', '?')} has required fields",
            False,
            f"missing: {required_tc_fields - set(tc.keys())}",
        )
        break
else:
    test("All test cases have required fields", True)

# Verify imports work
try:
    from agents.eval_runner.quality_score import QualityScoreCalculator
    from agents.eval_runner.evaluator import LLMJudgeEvaluator
    from agents.eval_runner.agent import build_eval_runner_graph
    from agents.orchestrator.agent import build_orchestrator_graph
    test("All Phase 2 modules importable", True)
except ImportError as e:
    test("All Phase 2 modules importable", False, str(e))


# ============================================================================
# TEST SECTION 11: LangSmith Tracing Module
# ============================================================================

print("\n[11/18] LangSmith Tracing Module")

from agents.tracing import (
    configure_tracing,
    get_graph_config,
    get_tracer_callbacks,
    is_tracing_enabled,
)

# Test configure_tracing without API key (should disable gracefully)
# Set key to empty string so load_dotenv(override=False) won't overwrite it from .env
os.environ["LANGSMITH_API_KEY"] = ""
os.environ.pop("LANGCHAIN_TRACING_V2", None)
os.environ["LANGSMITH_TRACING"] = "true"
# Reset module state
import agents.tracing
agents.tracing._tracing_configured = False

result_tracing = configure_tracing()
test(
    "configure_tracing returns False without API key",
    result_tracing is False,
)
test(
    "Tracing disabled without API key",
    not is_tracing_enabled(),
)

# Test configure_tracing with explicit disable
agents.tracing._tracing_configured = False
os.environ["LANGSMITH_TRACING"] = "false"
result_tracing_off = configure_tracing()
test(
    "configure_tracing returns False when disabled",
    result_tracing_off is False,
)

# Test get_graph_config (without tracing active)
os.environ["LANGCHAIN_TRACING_V2"] = "false"
config = get_graph_config(
    run_name="test-run",
    tags=["test"],
    metadata={"key": "value"},
)
test(
    "get_graph_config returns dict",
    isinstance(config, dict),
)
test(
    "Config has run_name",
    config.get("run_name") == "test-run",
)
test(
    "Config has tags",
    config.get("tags") == ["test"],
)
test(
    "Config has metadata",
    config.get("metadata") == {"key": "value"},
)
test(
    "No callbacks when tracing disabled",
    "callbacks" not in config,
)

# Test get_tracer_callbacks without tracing → empty list
callbacks = get_tracer_callbacks(run_name="test")
test(
    "get_tracer_callbacks empty when tracing off",
    callbacks == [],
)

# Test is_tracing_enabled
test(
    "is_tracing_enabled returns bool",
    isinstance(is_tracing_enabled(), bool),
)


# ============================================================================
# TEST SECTION 12: MCP Client Module
# ============================================================================

print("\n[12/18] MCP Client Module")

from agents.mcp_client import MCPStorageClient

# Test client instantiation
mcp_client = MCPStorageClient(storage_url="http://localhost:8000")
test(
    "MCPStorageClient instantiates",
    mcp_client is not None,
)

# Test load_test_cases (file-based, no server needed)
baseline_path_mcp = str(PROJECT_ROOT / "eval-datasets" / "baseline_v1.json")
loaded_cases = mcp_client.load_test_cases(baseline_path_mcp)
test(
    "MCP client loads test cases from file",
    len(loaded_cases) >= 10,
    f"got {len(loaded_cases)} cases",
)

# Test load_test_cases with relative path
loaded_rel = mcp_client.load_test_cases("eval-datasets/baseline_v1.json")
test(
    "MCP client handles relative paths",
    len(loaded_rel) >= 10,
)

# Test load_test_cases with missing file
try:
    mcp_client.load_test_cases("/nonexistent/test.json")
    test("MCP client raises on missing file", False)
except FileNotFoundError:
    test("MCP client raises FileNotFoundError for missing file", True)

# Test is_server_available (should be False if no server running)
available = mcp_client.is_server_available()
test(
    "is_server_available returns bool",
    isinstance(available, bool),
)

# Test save_eval_result with fallback (no server → direct backend)
_mcp_tmp = tempfile.mkdtemp(prefix="mcp_test_")
os.environ["STORAGE_DATA_DIR"] = _mcp_tmp
try:
    mcp_fallback_client = MCPStorageClient(storage_url="http://localhost:19999")  # unreachable
    save_res = mcp_fallback_client.save_eval_result(
        run_id="mcp-test-run",
        version_id="mcp-test-v1",
        scores={"quality_score": 7.5, "breakdown": {}},
        details=[{"test_case_id": "tc-1", "score": 7.5}],
    )
    test(
        "MCP client save_eval_result falls back to direct backend",
        "result_id" in save_res,
    )
finally:
    shutil.rmtree(_mcp_tmp, ignore_errors=True)
    os.environ.pop("STORAGE_DATA_DIR", None)

# Test MCP transport uses JSON-RPC 2.0 over /mcp (not /call-tool)
mock_http = MagicMock()
init_response = MagicMock()
init_response.status_code = 200
init_response.headers = {
    "mcp-session-id": "test-session",
    "content-type": "application/json",
}
init_response.json.return_value = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {"protocolVersion": "2024-11-05", "capabilities": {}},
}
initialized_response = MagicMock()
initialized_response.status_code = 200
initialized_response.headers = {"content-type": "application/json"}
initialized_response.json.return_value = {}
tool_response = MagicMock()
tool_response.status_code = 200
tool_response.headers = {"content-type": "application/json"}
tool_response.json.return_value = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [{"type": "text", "text": json.dumps({"ok": True})}],
    },
}
mock_http.post.side_effect = [init_response, initialized_response, tool_response]
rpc_client = MCPStorageClient(storage_url="http://localhost:8000")
with patch.object(rpc_client, "_get_http_client", return_value=mock_http):
    rpc_result = rpc_client._call_mcp_tool("list_versions", {"limit": 5})

rpc_call = mock_http.post.call_args
rpc_url = rpc_call.args[0] if rpc_call and rpc_call.args else ""
rpc_payload = rpc_call.kwargs.get("json", {}) if rpc_call else {}
test(
    "MCP client posts to /mcp endpoint",
    rpc_url.endswith("/mcp"),
    f"got {rpc_url}",
)
test(
    "MCP client uses JSON-RPC 2.0 tools/call",
    rpc_payload.get("jsonrpc") == "2.0"
    and rpc_payload.get("method") == "tools/call"
    and rpc_payload.get("params", {}).get("name") == "list_versions",
    f"got {rpc_payload}",
)
test(
    "MCP JSON-RPC call parses content result",
    rpc_result == {"ok": True},
    f"got {rpc_result}",
)
test(
    "MCP client initializes session before tools/call",
    mock_http.post.call_args_list[0].kwargs.get("json", {}).get("method") == "initialize"
    and mock_http.post.call_args_list[1].kwargs.get("json", {}).get("method") == "notifications/initialized"
    and mock_http.post.call_args_list[2].kwargs.get("json", {}).get("method") == "tools/call",
    f"got {[call.kwargs.get('json', {}).get('method') for call in mock_http.post.call_args_list]}",
)

# In production, MCP failures should fail closed unless fallback is explicitly allowed
strict_client = MCPStorageClient(storage_url="http://localhost:19999")
with patch.dict(os.environ, {"APP_ENV": "production"}, clear=False):
    try:
        strict_client.get_eval_results(version_id="v-prod")
        test("Production MCP failures do not silently fall back", False)
    except RuntimeError as exc:
        test(
            "Production MCP failures do not silently fall back",
            "fallback is disabled" in str(exc),
            str(exc),
        )


# ============================================================================
# TEST SECTION 13: Prompt Variants for Judge (P2-4)
# ============================================================================

print("\n[13/18] Prompt Variants for LLM Judge")

from agents.eval_runner.evaluator import (
    PROMPT_VARIANTS,
    DEFAULT_PROMPT_VARIANT,
    LLMJudgeEvaluator,
)

# Test all 3 variants exist
test(
    "3 prompt variants defined",
    len(PROMPT_VARIANTS) == 3,
    f"got {len(PROMPT_VARIANTS)}",
)
test(
    "Variant A exists",
    "A" in PROMPT_VARIANTS,
)
test(
    "Variant B exists",
    "B" in PROMPT_VARIANTS,
)
test(
    "Variant C exists",
    "C" in PROMPT_VARIANTS,
)

# Each variant is a tuple of (system_prompt, user_prompt)
for variant_name, (sys_p, usr_p) in PROMPT_VARIANTS.items():
    test(
        f"Variant {variant_name} system prompt is non-empty",
        len(sys_p) > 50,
    )
    test(
        f"Variant {variant_name} user prompt has placeholders",
        "{input_text}" in usr_p and "{expected_output}" in usr_p,
    )

# Default variant is valid
test(
    "DEFAULT_PROMPT_VARIANT is valid",
    DEFAULT_PROMPT_VARIANT in PROMPT_VARIANTS,
)

# Test evaluator initialization with each variant
for v in PROMPT_VARIANTS:
    evaluator_v = LLMJudgeEvaluator(api_key="test", prompt_variant=v)
    test(
        f"Evaluator initializes with variant {v}",
        evaluator_v._prompt_variant == v,
    )

# Test unknown variant falls back to default
evaluator_unknown = LLMJudgeEvaluator(api_key="test", prompt_variant="Z")
test(
    "Unknown variant falls back to default",
    evaluator_unknown._prompt_variant == DEFAULT_PROMPT_VARIANT,
)

# Test from_config with prompt_variant
_tmp_thresholds = tempfile.mktemp(suffix=".json")
Path(_tmp_thresholds).write_text(json.dumps({
    "judge_temperature": 0.0,
    "judge_passes": 2,
    "judge_anomaly_threshold": 2.0,
    "judge_prompt_variant": "B",
}))
evaluator_cfg_v = LLMJudgeEvaluator.from_config(
    thresholds_path=_tmp_thresholds,
    api_key="test",
)
test(
    "from_config loads judge_prompt_variant from config",
    evaluator_cfg_v._prompt_variant == "B",
)
os.unlink(_tmp_thresholds)

# Test prompt variant tester function exists
from agents.eval_runner.evaluator import test_prompt_variants
test(
    "test_prompt_variants function importable",
    callable(test_prompt_variants),
)


# ============================================================================
# TEST SECTION 14: Judge Call Audit Logger
# ============================================================================

print("\n[14/18] Judge Call Audit Logger")

from agents.eval_runner.audit_logger import JudgeAuditLogger

_audit_tmp = tempfile.mkdtemp(prefix="audit_test_")
try:
    audit_logger = JudgeAuditLogger(audit_dir=_audit_tmp)
    test(
        "JudgeAuditLogger instantiates",
        audit_logger is not None,
    )

    # Log a call
    audit_logger.log_call(
        run_id="test-run-123",
        test_case_id="tc-1",
        prompt_variant="A",
        model_name="gemini-2.5-flash",
        temperature=0.0,
        pass_num=1,
        attempt_num=1,
        input_text="Hello",
        expected_output="Xin chào",
        actual_output="Xin chào",
        raw_response='{"score": 9.0}',
        parsed_result={"score": 9.0, "accuracy": 9.0, "fluency": 9.0, "completeness": 9.0},
        latency_ms=150.5,
        success=True,
    )

    # Log a failed call
    audit_logger.log_call(
        run_id="test-run-123",
        test_case_id="tc-2",
        prompt_variant="A",
        model_name="gemini-2.5-flash",
        temperature=0.0,
        pass_num=1,
        attempt_num=1,
        input_text="How are you?",
        expected_output="Bạn khỏe không?",
        actual_output="",
        raw_response="",
        latency_ms=50.0,
        success=False,
        error="API timeout",
    )

    # Read audit logs back
    calls = audit_logger.get_calls(run_id="test-run-123")
    test(
        "Audit logger records calls",
        len(calls) == 2,
        f"got {len(calls)}",
    )

    # Verify call fields
    if calls:
        first_call = calls[0]
        test(
            "Audit record has timestamp",
            "timestamp" in first_call,
        )
        test(
            "Audit record has run_id",
            first_call.get("run_id") == "test-run-123",
        )
        test(
            "Audit record has prompt_variant",
            first_call.get("prompt_variant") == "A",
        )
        test(
            "Audit record has model",
            first_call.get("model") == "gemini-2.5-flash",
        )
        test(
            "Audit record has latency_ms",
            first_call.get("latency_ms") == 150.5,
        )
        test(
            "Audit record has success=True",
            first_call.get("success") is True,
        )
        test(
            "Audit record has parsed_result",
            first_call.get("parsed_result") is not None,
        )

    # Verify failed call
    if len(calls) >= 2:
        failed_call = calls[1]
        test(
            "Failed audit record has success=False",
            failed_call.get("success") is False,
        )
        test(
            "Failed audit record has error message",
            failed_call.get("error") == "API timeout",
        )

    # Test get_summary
    summary = audit_logger.get_summary()
    test(
        "get_summary returns total_calls",
        summary.get("total_calls") == 2,
    )
    test(
        "get_summary has success_rate",
        summary.get("success_rate") == 0.5,
    )
    test(
        "get_summary has avg_latency_ms",
        summary.get("avg_latency_ms") == 150.5,  # only 1 success with latency
    )

    # Filter by non-existent run_id
    empty_calls = audit_logger.get_calls(run_id="nonexistent")
    test(
        "get_calls filters by run_id",
        len(empty_calls) == 0,
    )

finally:
    shutil.rmtree(_audit_tmp, ignore_errors=True)


# ============================================================================
# TEST SECTION 15: Retry Logic in run_test_cases
# ============================================================================

print("\n[15/18] Retry Logic in run_test_cases")

from agents.eval_runner.agent import run_test_cases

# Test that run_test_cases returns empty for empty input
state_empty_rt: EvalRunnerState = {
    "test_cases": [],
    "target_app_url": "http://localhost:9999",
    "errors": [],
}
empty_result_rt = run_test_cases(state_empty_rt)
test(
    "run_test_cases returns empty for no test cases",
    empty_result_rt.get("test_results") == [],
)

# Test that run_test_cases handles connection errors with retry
# (target URL unreachable → will fail all retries)
state_retry: EvalRunnerState = {
    "test_cases": [
        {"id": "retry-tc-1", "input": "Hello", "expected_output": "Hola", "target_lang": "es"},
    ],
    "target_app_url": "http://localhost:19999",  # unreachable
    "errors": [],
}
retry_result = run_test_cases(state_retry)
results_list = retry_result.get("test_results", [])
test(
    "Retry logic produces result even on failure",
    len(results_list) == 1,
)
if results_list:
    test(
        "Failed test has status != completed",
        results_list[0].get("status") in ("error", "timeout", "failed"),
    )
    test(
        "Failed test has attempts field",
        results_list[0].get("attempts", 0) >= 1,
        f"got attempts={results_list[0].get('attempts')}",
    )
    test(
        "Failed test error is logged",
        len(retry_result.get("errors", [])) > 0,
    )
    test(
        "Error message mentions attempts",
        any("attempts" in e for e in retry_result.get("errors", [])),
    )


# ============================================================================
# TEST SECTION 16: State Graph Design Doc
# ============================================================================

print("\n[16/18] State Graph Design Doc (P2-2)")

design_doc_path = PROJECT_ROOT / "docs" / "state_graph_design.md"
test(
    "state_graph_design.md exists",
    design_doc_path.exists(),
)

if design_doc_path.exists():
    design_content = design_doc_path.read_text(encoding="utf-8")
    test(
        "Design doc has Eval Runner section",
        "Eval Runner Agent State Graph" in design_content,
    )
    test(
        "Design doc has Orchestrator section",
        "Eval Orchestrator Agent State Graph" in design_content,
    )
    test(
        "Design doc has Mermaid diagrams",
        "```mermaid" in design_content,
    )
    test(
        "Design doc has state schema tables",
        "EvalRunnerState" in design_content and "OrchestratorState" in design_content,
    )
    test(
        "Design doc has edge cases section",
        "Edge Cases" in design_content,
    )
    test(
        "Design doc has LangSmith tracing section",
        "LangSmith" in design_content,
    )
    test(
        "Design doc has end-to-end flow diagram",
        "End-to-End Flow" in design_content,
    )


# ============================================================================
# TEST SECTION 17: Requirements & Integration Checks
# ============================================================================

print("\n[17/18] Requirements & Integration Checks")

# agents/requirements.txt exists
agents_req = PROJECT_ROOT / "agents" / "requirements.txt"
test(
    "agents/requirements.txt exists",
    agents_req.exists(),
)
if agents_req.exists():
    req_content = agents_req.read_text(encoding="utf-8")
    test(
        "agents requirements has langgraph",
        "langgraph" in req_content,
    )
    test(
        "agents requirements has langsmith",
        "langsmith" in req_content,
    )
    test(
        "agents requirements has google-genai",
        "google-genai" in req_content,
    )
    test(
        "agents requirements has httpx",
        "httpx" in req_content,
    )
    test(
        "agents requirements has fastapi",
        "fastapi" in req_content,
    )

# Root requirements.txt has langsmith
root_req = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
test(
    "Root requirements.txt has langsmith",
    "langsmith" in root_req,
)

# Verify new modules importable
try:
    from agents.tracing import configure_tracing, get_graph_config
    from agents.mcp_client import MCPStorageClient
    from agents.eval_runner.audit_logger import JudgeAuditLogger
    from agents.eval_runner.evaluator import PROMPT_VARIANTS, test_prompt_variants
    test("All new Phase 2 modules importable", True)
except ImportError as e:
    test("All new Phase 2 modules importable", False, str(e))

# Verify LangSmith tracing is in agent run functions
from agents.eval_runner import agent as er_agent
import inspect
er_run_src = inspect.getsource(er_agent.run_eval)
test(
    "run_eval integrates LangSmith tracing",
    "configure_tracing" in er_run_src and "get_graph_config" in er_run_src,
)
test(
    "run_eval passes config to graph.invoke",
    "trace_config" in er_run_src,
)

from agents.orchestrator import agent as orc_agent
orc_run_src = inspect.getsource(orc_agent.run_pipeline)
test(
    "run_pipeline integrates LangSmith tracing",
    "configure_tracing" in orc_run_src and "get_graph_config" in orc_run_src,
)

# Verify MCP client is used in eval runner
er_load_src = inspect.getsource(er_agent.load_test_suite)
test(
    "load_test_suite uses MCPStorageClient",
    "MCPStorageClient" in er_load_src,
)
er_save_src = inspect.getsource(er_agent.save_results)
test(
    "save_results uses MCPStorageClient",
    "MCPStorageClient" in er_save_src,
)

# Verify retry logic in run_test_cases
er_testcases_src = inspect.getsource(er_agent.run_test_cases)
test(
    "run_test_cases has retry logic",
    "max_retries" in er_testcases_src and "attempt" in er_testcases_src,
)

# Verify evaluate_outputs passes audit context
er_eval_src = inspect.getsource(er_agent.evaluate_outputs)
test(
    "evaluate_outputs passes run_id to judge",
    "run_id" in er_eval_src,
)

# Verify systemd has orchestrator entry
systemd_path = PROJECT_ROOT / "scripts" / "systemd" / "services.conf"
if systemd_path.exists():
    sd_content = systemd_path.read_text(encoding="utf-8")
    test(
        "systemd has orchestrator service",
        "orchestrator" in sd_content.lower(),
    )


# ============================================================================
# TEST SECTION 18: Review Fixes Verification
# ============================================================================

print("\n[18/18] Review Fixes — All 10 Items")

# --- Fix #1: App down → score should be ~0, not 3.0 ---
# Simulate: all test cases failed, no latencies, no costs
result_app_down = calc.calculate(
    test_case_scores=[],
    latencies_ms=[],
    costs_usd=[],
    total_cases=50,
    skipped_cases=50,
)
test(
    "#1 App down: quality_score = 0.0 (not 3.0)",
    result_app_down.quality_score < 0.01,
    f"got {result_app_down.quality_score:.3f}",
)
test(
    "#1 App down: latency score = 0 (no data penalty)",
    result_app_down.breakdown["latency"]["score"] < 0.01,
)
test(
    "#1 App down: cost score = 0 (no data penalty)",
    result_app_down.breakdown["cost_efficiency"]["score"] < 0.01,
)
# Verify no_data flag in breakdown
test(
    "#1 App down: latency has no_data flag",
    result_app_down.breakdown["latency"].get("no_data") is True,
)
test(
    "#1 App down: cost has no_data flag",
    result_app_down.breakdown["cost_efficiency"].get("no_data") is True,
)

# Normal case should NOT have no_data flag
result_normal = calc.calculate(
    test_case_scores=[8.0] * 10,
    latencies_ms=[1500.0] * 10,
    costs_usd=[0.003] * 10,
)
test(
    "#1 Normal case: latency no_data is False",
    result_normal.breakdown["latency"].get("no_data") is False,
)

# --- Fix #2: Async execution (verify import and structure) ---
er_agent_src = inspect.getsource(er_agent.run_test_cases)
test(
    "#2 run_test_cases uses async (httpx.AsyncClient)",
    "AsyncClient" in er_agent_src,
)
test(
    "#2 run_test_cases uses semaphore for concurrency",
    "Semaphore" in er_agent_src,
)
import agents.eval_runner.agent as _er_mod
test(
    "#2 asyncio imported in eval runner agent",
    hasattr(_er_mod, "asyncio"),
)

# --- Fix #3: pass_threshold from QualityScoreCalculator ---
er_eval_src = inspect.getsource(er_agent.evaluate_outputs)
test(
    "#3 evaluate_outputs uses QualityScoreCalculator for threshold",
    "QualityScoreCalculator" in er_eval_src
    and "calculator.pass_threshold" in er_eval_src,
)
test(
    "#3 No hardcoded 6.0 threshold in evaluate_outputs",
    # Should not have ">= 6.0" or ">= 6" anywhere in the function
    ">= 6.0" not in er_eval_src and "= 6.0  # default" not in er_eval_src,
)

# --- Fix #4: test_prompt_variants skips missing actual_output ---
from agents.eval_runner.evaluator import test_prompt_variants
tpv_src = inspect.getsource(test_prompt_variants)
test(
    "#4 test_prompt_variants checks for actual_output",
    'tc.get("actual_output")' in tpv_src
    or "actual_output" in tpv_src,
)
test(
    "#4 test_prompt_variants skips/warns when no actual_output",
    "Skipping test case without actual_output" in tpv_src,
)

# --- Fix #5: target_lang not hardcoded "en" ---
test(
    "#5 run_test_cases gets target_lang from test case (not hardcoded 'en')",
    # Should resolve target_lang dynamically, not just tc.get("target_lang", "en")
    'tc.get("target_lang", "en")' not in er_agent_src,
)
test(
    "#5 run_test_cases has resolved_target_lang variable",
    "resolved_target_lang" in er_agent_src,
)

# --- Fix #6: Conditional edge after run_test_cases ---
graph_src = inspect.getsource(er_agent.build_eval_runner_graph)
test(
    "#6 Graph has conditional edge after run_test_cases",
    "should_continue_after_run" in graph_src,
)
test(
    "#6 All-fail skips evaluate_outputs → goes to aggregate",
    "aggregate_results" in graph_src and "completed" in graph_src,
)

# --- Fix #7: passed variable initialized early ---
qs_calc_src = inspect.getsource(QualityScoreCalculator.calculate)
# Check that passed=0 and pass_rate_pct=0.0 are initialized before the if block
passed_init_pos = qs_calc_src.find("passed = 0")
if_actual_run_pos = qs_calc_src.find("if actual_run > 0:")
test(
    "#7 'passed' initialized before if-block",
    passed_init_pos != -1 and passed_init_pos < if_actual_run_pos,
)
test(
    "#7 'pass_rate_pct' initialized before if-block",
    "pass_rate_pct = 0.0" in qs_calc_src,
)

# --- Fix #8: Audit logger has atomicity warning ---
audit_src = inspect.getsource(JudgeAuditLogger)
test(
    "#8 Audit logger documents append atomicity",
    "POSIX" in audit_src or "PIPE_BUF" in audit_src or "atomic" in audit_src,
)
test(
    "#8 Audit logger warns about NFS/Windows",
    "NFS" in audit_src or "Windows" in audit_src,
)

# --- Fix #9: Regex fallback logs warning ---
parser_src = inspect.getsource(LLMJudgeEvaluator._parse_json_response)
test(
    "#9 Regex fallback logs warning about mime type bypass",
    "response_mime_type" in parser_src or "falling back" in parser_src.lower(),
)

# --- Fix #10: Configurable truncation in audit logger ---
test(
    "#10 Audit logger has DEFAULT_TEXT_TRUNCATION",
    hasattr(JudgeAuditLogger, "DEFAULT_TEXT_TRUNCATION"),
)
test(
    "#10 DEFAULT_TEXT_TRUNCATION >= 1000",
    JudgeAuditLogger.DEFAULT_TEXT_TRUNCATION >= 1000,
)
# Verify __init__ accepts text_truncation param
import inspect as _insp
audit_init_sig = _insp.signature(JudgeAuditLogger.__init__)
test(
    "#10 __init__ accepts text_truncation parameter",
    "text_truncation" in audit_init_sig.parameters,
)
custom_logger = JudgeAuditLogger(
    audit_dir=str(PROJECT_ROOT / ".local-data" / "test-audit"),
    text_truncation=2000,
)
test(
    "#10 Custom truncation applied correctly",
    custom_logger._text_truncation == 2000,
)


# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 60)
total = _pass_count + _fail_count
if _fail_count == 0:
    print(f"ALL TESTS PASSED: {_pass_count}/{total}")
else:
    print(f"TESTS: {_pass_count} passed, {_fail_count} FAILED (total: {total})")
print("=" * 60)

sys.exit(0 if _fail_count == 0 else 1)
