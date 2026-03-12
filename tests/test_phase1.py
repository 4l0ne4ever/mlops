"""
Phase 1 — MCP Servers Unit & Integration Tests.

Tests all 3 MCP servers (Storage, Monitor, Deploy) using local backends directly.
No network calls — tests backends in-process for speed and reliability.

Run:
    python tests/test_phase1.py

Expected: all tests pass without AWS credentials or running servers.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project root and add server paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "storage"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "monitor"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "deploy"))

# Load configs for reference values
_local_config = json.loads(
    (PROJECT_ROOT / "configs" / "local.json").read_text(encoding="utf-8")
)

# ---------------------------------------------------------------------------
# Test harness (reuse pattern from test_phase0.py)
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
# Test 1: Storage Backend — save_prompt_version
# ============================================================================

print("=" * 60)
print("Phase 1 — MCP Servers Tests")
print("=" * 60)

print("\n[1/7] Storage Backend — save & get prompt version")

_tmp_dir = tempfile.mkdtemp(prefix="agentops-test-")

try:
    from storage_backend import LocalStorageBackend

    storage = LocalStorageBackend(data_dir=_tmp_dir)

    # Save a version
    save_result = storage.save_prompt_version(
        prompt_content='{"system_prompt": "test prompt", "version": "v1"}',
        version_label="v1-test",
        metadata={
            "model_name": "gemini-2.5-flash",
            "temperature": 0.3,
            "created_by": "test-user",
            "commit_sha": "abc123",
        },
    )

    test("save returns version_id", "version_id" in save_result)
    test("save returns s3_path", "s3_path" in save_result)
    test("save returns timestamp", "timestamp" in save_result)
    test(
        "version_id is UUID format",
        len(save_result["version_id"]) == 36 and save_result["version_id"].count("-") == 4,
    )

    # Get the version back
    version_id = save_result["version_id"]
    get_result = storage.get_prompt_version(version_id)

    test("get returns prompt_content", "prompt_content" in get_result)
    test("get returns metadata", "metadata" in get_result)
    test(
        "prompt_content matches",
        '"system_prompt": "test prompt"' in get_result["prompt_content"],
    )
    test(
        "metadata.model_name correct",
        get_result["metadata"]["model_name"] == "gemini-2.5-flash",
    )
    test(
        "metadata.status is active",
        get_result["metadata"]["status"] == "active",
    )

    # Get non-existent version
    try:
        storage.get_prompt_version("nonexistent-id")
        test("get non-existent raises error", False)
    except FileNotFoundError:
        test("get non-existent raises error", True)

except Exception as e:
    test("Storage backend loads", False, str(e))

# ============================================================================
# Test 2: Storage Backend — list_versions
# ============================================================================

print("\n[2/7] Storage Backend — list_versions")

try:
    # Save a second version
    save_result2 = storage.save_prompt_version(
        prompt_content='{"system_prompt": "updated prompt", "version": "v2"}',
        version_label="v2-improved",
        metadata={"model_name": "gemini-2.5-flash", "temperature": 0.5},
    )

    versions = storage.list_versions()
    test("list_versions returns list", isinstance(versions, list))
    test("list_versions has 2 items", len(versions) == 2)
    test(
        "newest version first",
        versions[0]["version_label"] == "v2-improved",
    )
    test(
        "each version has required fields",
        all(
            k in versions[0]
            for k in ("version_id", "version_label", "created_at", "status")
        ),
    )

    # Test limit
    limited = storage.list_versions(limit=1)
    test("limit=1 returns 1 item", len(limited) == 1)

    # Test status filter
    storage.update_version_status(save_result2["version_id"], "promoted")
    promoted = storage.list_versions(status_filter="promoted")
    test("status_filter=promoted works", len(promoted) == 1)
    test(
        "promoted version is correct",
        promoted[0]["version_id"] == save_result2["version_id"],
    )

except Exception as e:
    test("list_versions works", False, str(e))

# ============================================================================
# Test 3: Storage Backend — eval results
# ============================================================================

print("\n[3/7] Storage Backend — eval results")

try:
    eval_scores = {
        "quality_score": 7.965,
        "breakdown": {
            "task_completion": {"score": 8.5, "weight": 0.35},
            "output_quality": {"score": 7.2, "weight": 0.35},
            "latency": {"score": 7.5, "weight": 0.20},
            "cost_efficiency": {"score": 9.7, "weight": 0.10},
        },
    }
    eval_details = [
        {"test_case_id": "tc-1", "score": 8.5, "passed": True},
        {"test_case_id": "tc-2", "score": 5.2, "passed": False},
        {"test_case_id": "tc-3", "score": 7.8, "passed": True},
    ]

    eval_result = storage.save_eval_result(
        run_id="run-001",
        version_id=version_id,
        scores=eval_scores,
        details=eval_details,
    )

    test("save_eval returns result_id", "result_id" in eval_result)
    test("save_eval returns timestamp", "timestamp" in eval_result)

    # Get by run_id
    results_by_run = storage.get_eval_results(run_id="run-001")
    test("get by run_id returns 1 result", len(results_by_run) == 1)
    test(
        "quality_score matches",
        results_by_run[0]["quality_score"] == 7.965,
    )
    test(
        "total_test_cases correct",
        results_by_run[0]["total_test_cases"] == 3,
    )
    test(
        "passed_test_cases correct",
        results_by_run[0]["passed_test_cases"] == 2,
    )

    # Get by version_id
    results_by_version = storage.get_eval_results(version_id=version_id)
    test("get by version_id returns results", len(results_by_version) == 1)

    # Get non-existent
    empty = storage.get_eval_results(run_id="nonexistent")
    test("get non-existent run returns empty", len(empty) == 0)

except Exception as e:
    test("Eval results operations", False, str(e))

# ============================================================================
# Test 4: Monitor Backend — metrics
# ============================================================================

print("\n[4/7] Monitor Backend — metrics")

try:
    from monitor_backend import LocalMonitorBackend

    monitor = LocalMonitorBackend(data_dir=_tmp_dir)

    # Push metrics
    push_result = monitor.push_metric(
        metric_name="QualityScore",
        value=7.965,
        dimensions={"version_id": version_id, "environment": "staging"},
    )
    test("push_metric returns status=ok", push_result["status"] == "ok")
    test("push_metric returns timestamp", "timestamp" in push_result)

    # Push another datapoint
    monitor.push_metric(
        metric_name="QualityScore",
        value=8.245,
        dimensions={"version_id": "v2-id", "environment": "production"},
    )

    # Get all metrics for QualityScore
    all_metrics = monitor.get_metrics(metric_name="QualityScore")
    test("get_metrics returns 2 datapoints", len(all_metrics) == 2)
    test(
        "datapoints have timestamp and value",
        all("timestamp" in d and "value" in d for d in all_metrics),
    )

    # Get filtered by version_id
    filtered = monitor.get_metrics(
        metric_name="QualityScore", version_id=version_id
    )
    test("get_metrics filtered returns 1", len(filtered) == 1)
    test("filtered value correct", filtered[0]["value"] == 7.965)

    # Get non-existent metric
    empty = monitor.get_metrics(metric_name="NonExistent")
    test("non-existent metric returns empty", len(empty) == 0)

except Exception as e:
    test("Monitor metrics operations", False, str(e))

# ============================================================================
# Test 5: Monitor Backend — logs
# ============================================================================

print("\n[5/7] Monitor Backend — logs")

try:
    # Write logs
    monitor.write_log(
        log_group="pipeline-runs",
        message="Pipeline started for v2-test",
        level="INFO",
        extra={"version_id": "v2-test"},
    )
    monitor.write_log(
        log_group="pipeline-runs",
        message="Evaluation completed successfully",
        level="INFO",
    )
    monitor.write_log(
        log_group="pipeline-runs",
        message="Pipeline failed: connection timeout",
        level="ERROR",
    )
    monitor.write_log(
        log_group="decisions",
        message="Decision: AUTO_PROMOTE for v2-test",
        level="INFO",
    )

    # Get all logs for pipeline-runs
    logs = monitor.get_logs(log_group="pipeline-runs")
    test("get_logs returns 3 entries", len(logs) == 3)
    test("newest entry first", "failed" in logs[0]["message"])

    # Filter by pattern
    err_logs = monitor.get_logs(
        log_group="pipeline-runs", filter_pattern="failed"
    )
    test("filter_pattern works", len(err_logs) == 1)

    # Different log group
    decision_logs = monitor.get_logs(log_group="decisions")
    test("separate log groups work", len(decision_logs) == 1)

    # Non-existent log group
    empty_logs = monitor.get_logs(log_group="nonexistent")
    test("non-existent log group returns empty", len(empty_logs) == 0)

except Exception as e:
    test("Monitor logs operations", False, str(e))

# ============================================================================
# Test 6: Deploy Backend — deploy & rollback
# ============================================================================

print("\n[6/7] Deploy Backend — deploy & rollback")

try:
    from deploy_backend import LocalDeployBackend

    deploy = LocalDeployBackend(data_dir=_tmp_dir, local_config=_local_config)

    # Deploy to staging
    deploy_result = deploy.deploy_version(
        version_id=version_id, environment="staging"
    )
    test("deploy returns deployment_id", "deployment_id" in deploy_result)
    test("deploy status is deployed", deploy_result["status"] == "deployed")
    test("deploy returns endpoint_url", "endpoint_url" in deploy_result)
    test(
        "staging endpoint matches config",
        deploy_result["endpoint_url"]
        == _local_config["target_app"]["staging_url"],
    )

    # Deploy to production
    deploy_prod = deploy.deploy_version(
        version_id=version_id, environment="production"
    )
    test("production deploy succeeds", deploy_prod["status"] == "deployed")

    # Deploy with invalid environment
    deploy_bad = deploy.deploy_version(
        version_id=version_id, environment="invalid"
    )
    test("invalid env returns failed", deploy_bad["status"] == "failed")

    # Rollback
    rollback_result = deploy.rollback_version(
        target_version_id="previous-version-id"
    )
    test("rollback returns deployment_id", "deployment_id" in rollback_result)
    test(
        "rollback status is rolled_back",
        rollback_result["status"] == "rolled_back",
    )

except Exception as e:
    test("Deploy operations", False, str(e))

# ============================================================================
# Test 7: Deploy Backend — deployment status
# ============================================================================

print("\n[7/7] Deploy Backend — deployment status")

try:
    # Get status by environment
    staging_status = deploy.get_deployment_status(environment="staging")
    test(
        "staging status has version_id",
        staging_status["current_version_id"] == version_id,
    )
    test(
        "staging status is deployed",
        staging_status["status"] == "deployed",
    )

    production_status = deploy.get_deployment_status(environment="production")
    test(
        "production shows rollback version",
        production_status["current_version_id"] == "previous-version-id",
    )
    test(
        "production status is rolled_back",
        production_status["status"] == "rolled_back",
    )

    # Get status by deployment_id
    dep_id = deploy_result["deployment_id"]
    by_id = deploy.get_deployment_status(deployment_id=dep_id)
    test(
        "get by deployment_id finds record",
        by_id.get("deployment_id") == dep_id,
    )

    # Get status with no params
    no_params = deploy.get_deployment_status()
    test(
        "no params returns error",
        "error" in no_params,
    )

    # Get invalid environment
    bad_env = deploy.get_deployment_status(environment="invalid")
    test("invalid env returns error", "error" in bad_env)

except Exception as e:
    test("Deployment status operations", False, str(e))

# ============================================================================
# Cleanup & Results
# ============================================================================

shutil.rmtree(_tmp_dir, ignore_errors=True)

print()
print("=" * 60)
total = _pass_count + _fail_count
print(f"Results: {_pass_count} passed, {_fail_count} failed, {total} total")
if _fail_count == 0:
    print("\U0001f389 ALL TESTS PASSED")
else:
    print(f"\u26a0\ufe0f  {_fail_count} test(s) FAILED")
print("=" * 60)

sys.exit(0 if _fail_count == 0 else 1)
