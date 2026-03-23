"""
Migration tests for the new public `agentops` framework API.

Run:
  python tests/test_migration_public_api.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


_pass = 0
_fail = 0


def test(name: str, cond: bool, detail: str = "") -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  ✅ {name}")
    else:
        _fail += 1
        msg = f"  ❌ {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


print("Phase Migration — Public API")
print("=" * 32)


print("\n[1/5] configure() creates absolute APP_CONFIG and resolves eval dataset")
os.environ.pop("APP_CONFIG", None)

agentops_tmp_data_dir = tempfile.mkdtemp(prefix="agentops-public-")

# Import after env tweaks (to keep the test deterministic)
import agentops  # noqa: E402

agentops.configure(
    target_app_url="http://localhost:9000",
    storage_data_dir=agentops_tmp_data_dir,
)

app_cfg_path = os.environ.get("APP_CONFIG", "")
test("APP_CONFIG is set", bool(app_cfg_path))
test("APP_CONFIG is absolute", bool(app_cfg_path) and Path(app_cfg_path).is_absolute())

cfg = agentops.get_config()
test(
    "Default test_suite_path points inside eval datasets (repo or package)",
    ("eval_datasets" in cfg.test_suite_path) or ("eval-datasets" in cfg.test_suite_path),
)
test("Default backend is local", cfg.backend == "local")


print("\n[2/5] EvalRunner wrapper maps internal run_eval output into typed result")
dummy_eval_result: dict[str, Any] = {
    "run_id": "run-x",
    "version_id": "v-x",
    "status": "completed",
    "result_id": "result-x",
    "quality_score": {
        "quality_score": 8.25,
        "breakdown": {"task_completion": {"score": 8.0}},
        "metadata": {"version_id": "v-x"},
        "warnings": ["w1"],
    },
}

with patch("agents.eval_runner.agent.run_eval", return_value=dummy_eval_result):
    runner = agentops.EvalRunner()
    out = runner.run_eval(version_id="v-x")

test("EvalRunner returns EvalRunResult-like object", hasattr(out, "quality_score"))
test("quality_score propagated", abs(out.quality_score.quality_score - 8.25) < 1e-6)
test("run_id propagated", out.run_id == "run-x")
test("status propagated", out.status == "completed")


print("\n[3/5] Orchestrator wrapper maps internal run_pipeline output")
dummy_orch_result: dict[str, Any] = {
    "run_id": "orch-run-x",
    "status": "completed",
    "quality_score": 6.5,
    "comparison_report": {"verdict": "IMPROVED"},
    "decision": {"decision": "AUTO_PROMOTE"},
}

with patch("agents.orchestrator.agent.run_pipeline", return_value=dummy_orch_result):
    orch = agentops.Orchestrator()
    out2 = orch.run_pipeline(run_id="orch-run-x")

test("Orchestrator result has comparison_report", isinstance(out2.comparison_report, dict))
test("Orchestrator decision propagated", out2.decision.get("decision") == "AUTO_PROMOTE")


print("\n[4/5] StorageClient local mode uses LocalStorageBackend (no MCP call_tool)")
with patch("agentops.mcp.clients.call_tool", side_effect=AssertionError("call_tool should not be called")):
    with patch("agentops.mcp.clients.LocalStorageBackend") as LS:
        backend = LS.return_value
        backend.list_versions.return_value = [{"version_label": "v1"}]

        sc = agentops.mcp.StorageClient()
        versions = sc.list_versions(limit=1)

test("StorageClient.list_versions returns backend result", versions == [{"version_label": "v1"}])
test("LocalStorageBackend instantiated", LS.called)


print("\n[5/5] DeployClient local mode passes APP_CONFIG target_app URLs into LocalDeployBackend")
with patch("agentops.mcp.clients.LocalDeployBackend") as LD:
    backend = LD.return_value
    backend.deploy_version.return_value = {"status": "deployed", "deployment_id": "dep-1", "endpoint_url": "http://x"}

    dc = agentops.mcp.DeployClient()
    dc.deploy_version(version_id="v1", environment="staging")

    # LocalDeployBackend local_config should include target_app.* keys
    passed_local_config = LD.call_args.kwargs.get("local_config", {})
    test("DeployClient passes target_app section", "target_app" in passed_local_config)
    test("DeployClient passes staging_url", "staging_url" in passed_local_config.get("target_app", {}))


print()
print(f"Public API Migration Results: {_pass} passed, {_fail} failed")
if _fail:
    sys.exit(1)
sys.exit(0)

