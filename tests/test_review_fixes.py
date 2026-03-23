"""
Review Fixes — Unit tests for code-review fix batches.

Round 1 (18 issues on Phases 0-2):
    #1  CORS env crash (os.environ.get with default)
    #2  Batch blocking (asyncio.to_thread concurrency)
    #3  Config KeyError (dict .get() with defaults)
    #4  source_lang "auto" → "vi" default
    #5  TOCTOU lock race (atomic O_CREAT|O_EXCL)
    #6  Production config differs from local
    #7  Lock leak on exception (try/finally)
    #8  MCP server module-level config guarded
    #9  audit_logger init in __init__
    #10 time_range filtering implemented
    #11 httpx client reused
    #12 Batch partial failure handling
    #13 Deprecated asyncio.get_event_loop → get_running_loop
    #14 Translator assert → TranslationError
    #15 JSON parsing guard in storage save_eval_result
    #16 Production config URLs (combined with #6)
    #17 Requirements pinned with ~=
    #18 App asserts → HTTPException

Round 2 (7 P1/P2 findings on Phase 3 components):
    R2-1 (P1) Comparator breakdown entries are dicts {score,weight,raw_value}
    R2-2 (P1) compare_versions_node quality_score is a nested dict
    R2-3 (P2) MCPStorageClient.list_versions() via MCP-first + fallback
    R2-4 (P2) MCPDeployClient and MCPMonitorClient classes added
    R2-5 (P2) Decision agent routes through MCP clients, not direct backends
    R2-6 (P2) eval-datasets/ classified as relevant in parse_change
    R2-7 (P2) /translate endpoint wraps sync call in asyncio.to_thread

Run:
    python tests/test_review_fixes.py

Expected: all tests pass without API keys or running servers.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project root
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "agents"))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "eval_runner"))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "orchestrator"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "storage"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "deploy"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "monitor"))

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

_pass_count = 0
_fail_count = 0


def test(name: str, condition: bool, detail: str = "") -> None:
    global _pass_count, _fail_count
    if condition:
        _pass_count += 1
        print(f"  ✅ {name}")
    else:
        _fail_count += 1
        msg = f"  ❌ {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


# ============================================================================
# FIX #1: CORS crash — os.environ.get with default
# ============================================================================
print("\n--- Fix #1: CORS env crash ---")

app_source = (PROJECT_ROOT / "target-app" / "app.py").read_text(encoding="utf-8")

test(
    "#1 No os.environ[] for CORS_ALLOWED_ORIGINS",
    'os.environ["CORS_ALLOWED_ORIGINS"]' not in app_source,
    "Still uses os.environ[] instead of os.environ.get()",
)
test(
    "#1 Uses os.environ.get() for CORS_ALLOWED_ORIGINS",
    'os.environ.get("CORS_ALLOWED_ORIGINS"' in app_source,
)
test(
    "#1 Has default value for CORS origins",
    "http://localhost:3000" in app_source,
)

# ============================================================================
# FIX #2: Batch blocking — asyncio.to_thread concurrency
# ============================================================================
print("\n--- Fix #2: Batch non-blocking concurrency ---")

test(
    "#2 import asyncio present in app.py",
    "import asyncio" in app_source,
)
test(
    "#2 Uses asyncio.to_thread for batch items",
    "asyncio.to_thread" in app_source,
)
test(
    "#2 Uses asyncio.gather for concurrent execution",
    "asyncio.gather" in app_source,
)

# ============================================================================
# FIX #3: Config KeyError — .get() with defaults
# ============================================================================
print("\n--- Fix #3: Config .get() with defaults ---")

# Source analysis only — no need to import the module
config_source = (PROJECT_ROOT / "target-app" / "config.py").read_text(encoding="utf-8")

test(
    "#3 No direct dict[key] for model_name",
    '["model_name"]' not in config_source,
)
test(
    "#3 Uses .get() for model_name with default",
    ".get(\"model_name\"" in config_source,
)
test(
    "#3 Uses .get() for temperature with default",
    ".get(\"temperature\"" in config_source,
)
test(
    "#3 Uses .get() for max_tokens with default",
    ".get(\"max_tokens\"" in config_source,
)
test(
    "#3 Uses .get() for log level with nested .get()",
    '.get("logging", {}).get("level"' in config_source
    or '.get("level"' in config_source,
)

# ============================================================================
# FIX #4: source_lang "auto" → "vi" default
# ============================================================================
print("\n--- Fix #4: source_lang default fixed ---")

eval_agent_source = (
    PROJECT_ROOT / "agents" / "eval_runner" / "agent.py"
).read_text(encoding="utf-8")

test(
    "#4 No source_lang default 'auto' in eval runner",
    "\"source_lang\", \"auto\"" not in eval_agent_source
    and "'source_lang', 'auto'" not in eval_agent_source,
    "Still defaults to 'auto'",
)
test(
    "#4 source_lang defaults to 'vi'",
    '"source_lang", "vi"' in eval_agent_source
    or "'source_lang', 'vi'" in eval_agent_source,
)

# ============================================================================
# FIX #5: TOCTOU lock race — atomic O_CREAT|O_EXCL
# ============================================================================
print("\n--- Fix #5: Atomic lock acquisition ---")

orch_source = (
    PROJECT_ROOT / "agents" / "orchestrator" / "agent.py"
).read_text(encoding="utf-8")

test(
    "#5 Uses os.O_CREAT | os.O_EXCL for atomic lock",
    "os.O_CREAT" in orch_source and "os.O_EXCL" in orch_source,
)
test(
    "#5 Catches FileExistsError for lock contention",
    "FileExistsError" in orch_source,
)

# Functional test: _acquire_lock uses atomic file creation
from agent import _acquire_lock, _release_lock, _LOCK_DIR

_test_lock_dir = Path(tempfile.mkdtemp()) / "lock-test"
# Temporarily patch _LOCK_DIR
import agents.orchestrator.agent as _orch_mod

_orig_lock_dir = _orch_mod._LOCK_DIR
_orch_mod._LOCK_DIR = _test_lock_dir

try:
    run1 = "test-run-1"
    run2 = "test-run-2"
    acquired1 = _acquire_lock(run1)
    test("#5 First lock acquisition succeeds", acquired1)

    acquired2 = _acquire_lock(run2)
    test("#5 Second lock acquisition fails (locked)", not acquired2)

    _release_lock(run1)
    acquired3 = _acquire_lock(run2)
    test("#5 Lock reacquired after release", acquired3)
    _release_lock(run2)
finally:
    _orch_mod._LOCK_DIR = _orig_lock_dir
    shutil.rmtree(_test_lock_dir.parent, ignore_errors=True)

# ============================================================================
# FIX #6/#16: Production config differs from local
# ============================================================================
print("\n--- Fix #6/#16: Production config distinct ---")

prod_config = json.loads(
    (PROJECT_ROOT / "configs" / "production.json").read_text(encoding="utf-8")
)
local_config = json.loads(
    (PROJECT_ROOT / "configs" / "local.json").read_text(encoding="utf-8")
)

test(
    "#6 Production environment is 'production'",
    prod_config.get("environment") == "production",
)
test(
    "#6 Local environment is 'local'",
    local_config.get("environment") == "local",
)
test(
    "#16 Production URLs differ from localhost",
    "localhost" not in prod_config["target_app"]["production_url"],
    f"Got: {prod_config['target_app']['production_url']}",
)
test(
    "#16 Production MCP URLs differ from localhost",
    "localhost" not in prod_config["mcp_servers"]["storage"],
    f"Got: {prod_config['mcp_servers']['storage']}",
)
test(
    "#6 Production log level is INFO (not DEBUG)",
    prod_config.get("logging", {}).get("level") == "INFO",
)
test(
    "#6 Local log level is DEBUG",
    local_config.get("logging", {}).get("level") == "DEBUG",
)

# ============================================================================
# FIX #7: Lock leak on exception — try/finally
# ============================================================================
print("\n--- Fix #7: Lock release on exception ---")

# Check that run_pipeline wraps graph.invoke in try/except with _release_lock
test(
    "#7 run_pipeline has try block around graph.invoke",
    "try:" in orch_source.split("def run_pipeline")[1]
    if "def run_pipeline" in orch_source
    else False,
)
test(
    "#7 run_pipeline has _release_lock in except/finally",
    "_release_lock" in orch_source.split("def run_pipeline")[1]
    if "def run_pipeline" in orch_source
    else False,
)

# ============================================================================
# FIX #8: MCP server module-level config guarded
# ============================================================================
print("\n--- Fix #8: MCP server config load guarded ---")

storage_server_source = (
    PROJECT_ROOT / "mcp-servers" / "storage" / "server.py"
).read_text(encoding="utf-8")
deploy_server_source = (
    PROJECT_ROOT / "mcp-servers" / "deploy" / "server.py"
).read_text(encoding="utf-8")

test(
    "#8 Storage server config load has try/except",
    "try:" in storage_server_source.split("_local_config")[1].split("_data_dir")[0],
)
test(
    "#8 Storage server catches FileNotFoundError",
    "FileNotFoundError" in storage_server_source,
)
test(
    "#8 Deploy server config load has try/except",
    "try:" in deploy_server_source.split("_local_config")[1].split("_data_dir")[0],
)
test(
    "#8 Deploy server catches FileNotFoundError",
    "FileNotFoundError" in deploy_server_source,
)

# ============================================================================
# FIX #9: audit_logger init in __init__
# ============================================================================
print("\n--- Fix #9: audit_logger initialized in __init__ ---")

from eval_runner.evaluator import LLMJudgeEvaluator

evaluator = LLMJudgeEvaluator(api_key="test-key")
test(
    "#9 _audit_logger attribute exists on new instance",
    hasattr(evaluator, "_audit_logger"),
)
test(
    "#9 _audit_logger is None before _ensure_client",
    evaluator._audit_logger is None,
)
test(
    "#9 No hasattr() check needed (attribute always exists)",
    "_audit_logger" in evaluator.__dict__,
)

# ============================================================================
# FIX #10: time_range filtering implemented
# ============================================================================
print("\n--- Fix #10: time_range filtering ---")

monitor_source = (
    PROJECT_ROOT / "mcp-servers" / "monitor" / "monitor_backend.py"
).read_text(encoding="utf-8")

test(
    "#10 No TODO comment for time_range",
    "TODO: implement actual time_range" not in monitor_source,
)
test(
    "#10 Has _cutoff_for_range helper",
    "_cutoff_for_range" in monitor_source,
)
test(
    "#10 Uses timedelta for time calculation",
    "timedelta" in monitor_source,
)

# Functional test: time_range filtering
from mcp_servers.monitor.monitor_backend import LocalMonitorBackend, _cutoff_for_range
from datetime import datetime, timedelta, timezone

_test_monitor_dir = tempfile.mkdtemp()
try:
    backend = LocalMonitorBackend(data_dir=_test_monitor_dir)

    # Push a metric now
    backend.push_metric("test_metric", 1.0, {"version_id": "v1"})
    # Push a metric with old timestamp (manually)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    metric_dir = Path(_test_monitor_dir) / "metrics" / "test_metric"
    with open(metric_dir / "datapoints.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "metric_name": "test_metric",
            "value": 0.5,
            "dimensions": {"version_id": "v1"},
            "timestamp": old_ts,
        }) + "\n")

    all_metrics = backend.get_metrics("test_metric", time_range="last_7d")
    recent_metrics = backend.get_metrics("test_metric", time_range="last_24h")

    test(
        "#10 get_metrics last_7d returns all data (2 points)",
        len(all_metrics) == 2,
        f"Got {len(all_metrics)} instead of 2",
    )
    test(
        "#10 get_metrics last_24h filters old data (1 point)",
        len(recent_metrics) == 1,
        f"Got {len(recent_metrics)} instead of 1",
    )

    # Test _cutoff helper
    cutoff = _cutoff_for_range("last_24h")
    test("#10 _cutoff_for_range returns datetime", cutoff is not None)
    test(
        "#10 _cutoff_for_range returns None for bad format",
        _cutoff_for_range("bogus") is None,
    )
finally:
    shutil.rmtree(_test_monitor_dir, ignore_errors=True)

# ============================================================================
# FIX #11: httpx client reuse
# ============================================================================
print("\n--- Fix #11: httpx client reuse ---")

mcp_client_source = (
    PROJECT_ROOT / "agents" / "mcp_client.py"
).read_text(encoding="utf-8")

test(
    "#11 No 'with httpx.Client' per-call pattern",
    "with httpx.Client(" not in mcp_client_source,
)
test(
    "#11 Has _http_client attribute",
    "_http_client" in mcp_client_source,
)
test(
    "#11 Has _get_http_client method",
    "_get_http_client" in mcp_client_source,
)
test(
    "#11 Has close() method for cleanup",
    "def close(self)" in mcp_client_source,
)

# Functional test
from agents.mcp_client import MCPStorageClient

client = MCPStorageClient(storage_url="http://localhost:9999")
test("#11 _http_client is None initially", client._http_client is None)
http_client = client._get_http_client()
test("#11 _get_http_client creates client", http_client is not None)
same_client = client._get_http_client()
test("#11 _get_http_client returns same instance", http_client is same_client)
client.close()
test("#11 close() closes the client", http_client.is_closed)

# ============================================================================
# FIX #12: Batch partial failure handling
# ============================================================================
print("\n--- Fix #12: Batch partial failure handling ---")

test(
    "#12 Uses return_exceptions=True in gather",
    "return_exceptions=True" in app_source,
)
test(
    "#12 Checks isinstance(outcome, Exception)",
    "isinstance(outcome, Exception)" in app_source
    or "isinstance(outcome, BaseException)" in app_source,
)
test(
    "#12 Collects errors list for failed items",
    "errors.append" in app_source,
)

# ============================================================================
# FIX #13: Deprecated asyncio.get_event_loop → get_running_loop
# ============================================================================
print("\n--- Fix #13: Deprecated asyncio.get_event_loop ---")

test(
    "#13 No asyncio.get_event_loop() in orchestrator",
    "asyncio.get_event_loop()" not in orch_source,
)
test(
    "#13 Uses asyncio.get_running_loop() instead",
    "asyncio.get_running_loop()" in orch_source,
)

# ============================================================================
# FIX #14: Translator assert → TranslationError
# ============================================================================
print("\n--- Fix #14: Translator assert replaced ---")

translator_source = (
    PROJECT_ROOT / "target-app" / "translator.py"
).read_text(encoding="utf-8")

test(
    "#14 No 'assert self._client' in translator",
    "assert self._client" not in translator_source,
)
test(
    "#14 Raises TranslationError for unconfigured client",
    "raise TranslationError" in translator_source,
)

# ============================================================================
# FIX #15: JSON parsing guard in storage save_eval_result
# ============================================================================
print("\n--- Fix #15: JSON parsing guard ---")

test(
    "#15 save_eval_result has try/except for scores JSON",
    "Invalid scores JSON" in storage_server_source
    or "JSONDecodeError" in storage_server_source,
)
test(
    "#15 save_eval_result has try/except for details JSON",
    "Invalid details JSON" in storage_server_source,
)

# ============================================================================
# FIX #17: Requirements pinned with ~= (compatible release)
# ============================================================================
print("\n--- Fix #17: Requirements version pinning ---")

req_source = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")

# Count ~= pins vs >= pins (excluding langsmith which stays >=)
tilde_pins = len(re.findall(r"~=", req_source))
gte_pins = len(re.findall(r">=", req_source))

test(
    "#17 Majority of packages use ~= (compatible release)",
    tilde_pins > gte_pins,
    f"~={tilde_pins} vs >={gte_pins}",
)
test(
    "#17 fastapi uses ~= (compatible release)",
    "fastapi~=" in req_source,
)
test(
    "#17 google-genai uses ~= (compatible release)",
    "google-genai~=" in req_source,
)
test(
    "#17 mcp uses ~= (compatible release)",
    "mcp~=" in req_source,
)

# ============================================================================
# FIX #18: App asserts → HTTPException(503)
# ============================================================================
print("\n--- Fix #18: App asserts replaced with HTTPException ---")

# Check no assert statements in route handlers
tree = ast.parse(app_source)
assert_count = sum(1 for node in ast.walk(tree) if isinstance(node, ast.Assert))
test(
    "#18 No assert statements in app.py",
    assert_count == 0,
    f"Found {assert_count} assert(s)",
)
test(
    "#18 Uses HTTPException(503) for uninitialized service",
    'status_code=503, detail="Service not initialized"' in app_source,
)


# ============================================================================
# CODE REVIEW ROUND 2 — P1 & P2 Findings (Phase 3 components)
# ============================================================================

# ============================================================================
# R2-1 (P1): Comparator breakdown entries are dicts {score, weight, raw_value}
# ============================================================================
print("\n--- R2-1 (P1): Comparator handles dict breakdown entries ---")

comparator_source = (
    PROJECT_ROOT / "agents" / "comparator" / "agent.py"
).read_text(encoding="utf-8")

test(
    "R2-1 compare_dimensions has isinstance(new_val, dict) guard",
    "isinstance(new_val, dict)" in comparator_source,
)
test(
    "R2-1 compare_dimensions has isinstance(current_val, dict) guard",
    "isinstance(current_val, dict)" in comparator_source,
)
test(
    "R2-1 compare_dimensions extracts .get('score', 0.0) for dict entries",
    '.get("score", 0.0)' in comparator_source or ".get('score', 0.0)" in comparator_source,
)
test(
    "R2-1 detect_regression also guards old_val and new_val",
    comparator_source.count("isinstance") >= 4,  # 2 in compare_dims + 2 in detect_regression
    f"isinstance count={comparator_source.count('isinstance')}",
)

# Functional test: compare_versions with dict breakdowns
try:
    from agents.comparator.agent import compare_versions as _compare_versions

    def _dict_scores(qs: float, tc: float, oq: float, lat: float, ce: float) -> dict:
        return {
            "quality_score": qs,
            "score_breakdown": {
                "task_completion": {"score": tc, "weight": 0.35, "raw_value": tc},
                "output_quality": {"score": oq, "weight": 0.35, "raw_value": oq},
                "latency": {"score": lat, "weight": 0.15, "raw_value": lat},
                "cost_efficiency": {"score": ce, "weight": 0.15, "raw_value": ce},
            },
        }

    r2_1_improved = _compare_versions(
        v_new_id="v_r21_new", v_current_id="v_r21_cur",
        v_new_scores=_dict_scores(8.5, 9.0, 8.5, 8.0, 8.5),
        v_current_scores=_dict_scores(7.0, 7.0, 7.0, 7.0, 7.0),
    )
    test(
        "R2-1 functional: dict breakdowns → IMPROVED verdict",
        r2_1_improved.get("verdict") == "IMPROVED",
        f"got {r2_1_improved.get('verdict')}",
    )
    test(
        "R2-1 functional: dict breakdown delta = 1.5",
        r2_1_improved.get("delta") == 1.5,
        f"got {r2_1_improved.get('delta')}",
    )
    r2_1_crit = _compare_versions(
        v_new_id="v_r21_crit", v_current_id="v_r21_base",
        v_new_scores=_dict_scores(6.0, 7.0, 7.0, 5.5, 7.0),
        v_current_scores=_dict_scores(7.0, 7.0, 7.0, 7.0, 7.0),
    )
    test(
        "R2-1 functional: dict breakdowns → CRITICAL_REGRESSION",
        r2_1_crit.get("verdict") == "CRITICAL_REGRESSION",
        f"got {r2_1_crit.get('verdict')}",
    )
    # regression entries should carry floats, not dicts
    regs_r21 = r2_1_crit.get("regressions", [])
    test(
        "R2-1 functional: regression 'old' field is float (not dict)",
        all(isinstance(r["old"], float) for r in regs_r21) if regs_r21 else False,
        f"types={[type(r['old']).__name__ for r in regs_r21]}",
    )
    test(
        "R2-1 functional: regression 'new' field is float (not dict)",
        all(isinstance(r["new"], float) for r in regs_r21) if regs_r21 else False,
        f"types={[type(r['new']).__name__ for r in regs_r21]}",
    )
except Exception as e:
    for _ in range(6):
        test(f"R2-1 functional (skipped — {e})", False)


# ============================================================================
# R2-2 (P1): compare_versions_node handles nested quality_score dict
# ============================================================================
print("\n--- R2-2 (P1): compare_versions_node nested quality_score ---")

orch_source_r2 = (
    PROJECT_ROOT / "agents" / "orchestrator" / "agent.py"
).read_text(encoding="utf-8")

test(
    "R2-2 compare_versions_node checks isinstance(qs_dict, dict)",
    "isinstance(qs_dict, dict)" in orch_source_r2,
)
test(
    "R2-2 compare_versions_node extracts qs_dict.get('quality_score')",
    "qs_dict.get(\"quality_score\"" in orch_source_r2
    or "qs_dict.get('quality_score'" in orch_source_r2,
)
test(
    "R2-2 compare_versions_node extracts qs_dict.get('breakdown')",
    "qs_dict.get(\"breakdown\"" in orch_source_r2
    or "qs_dict.get('breakdown'" in orch_source_r2,
)

# Functional test: nested quality_score
try:
    import tempfile as _tempfile, shutil as _shutil
    from unittest.mock import patch as _patch

    _r22_tmp = _tempfile.mkdtemp(prefix="r22_")
    try:
        from agents.orchestrator.agent import compare_versions_node as _cvn

        with _patch.dict(os.environ, {"STORAGE_DATA_DIR": _r22_tmp}):
            cvn_nested = _cvn({
                "run_id": "r22_nested",
                "version_id": "v_r22",
                "eval_result": {
                    "version_id": "v_r22",
                    "quality_score": {
                        "quality_score": 8.5,
                        "breakdown": {
                            "task_completion": {"score": 9.0, "weight": 0.35, "raw_value": 9.0},
                            "output_quality": {"score": 8.5, "weight": 0.35, "raw_value": 8.5},
                            "latency": {"score": 8.0, "weight": 0.15, "raw_value": 8.0},
                            "cost_efficiency": {"score": 8.0, "weight": 0.15, "raw_value": 8.0},
                        },
                        "metadata": {},
                    },
                },
                "quality_score": 8.5,
                "errors": [],
            })
        r22_report = cvn_nested.get("comparison_report", {})
        test(
            "R2-2 functional: nested quality_score → does not crash",
            isinstance(r22_report, dict),
        )
        test(
            "R2-2 functional: nested quality_score → has verdict",
            "verdict" in r22_report,
        )
        test(
            "R2-2 functional: delta extracted from nested dict (8.5, not 0)",
            r22_report.get("delta") == 8.5,
            f"got delta={r22_report.get('delta')}",
        )
    finally:
        _shutil.rmtree(_r22_tmp, ignore_errors=True)
except Exception as e:
    for _ in range(3):
        test(f"R2-2 functional (skipped — {e})", False)


# ============================================================================
# R2-3 (P2): MCPStorageClient.list_versions() via MCP-first + fallback
# ============================================================================
print("\n--- R2-3 (P2): MCPStorageClient.list_versions() ---")

test(
    "R2-3 mcp_client.py defines list_versions method",
    "def list_versions(" in mcp_client_source,
)
test(
    "R2-3 list_versions has MCP-first call (_call_mcp_tool)",
    mcp_client_source.count('_call_mcp_tool("list_versions"') >= 1
    or mcp_client_source.count("_call_mcp_tool('list_versions'") >= 1,
)
test(
    "R2-3 list_versions has local backend fallback",
    "backend.list_versions" in mcp_client_source,
)
test(
    "R2-3 list_versions accepts limit and status_filter params",
    "limit" in mcp_client_source and "status_filter" in mcp_client_source,
)

# Functional: list_versions via local fallback (no MCP server running)
try:
    import tempfile as _tf, shutil as _sh
    _r23_tmp = _tf.mkdtemp(prefix="r23_")
    try:
        with _patch.dict(os.environ, {"STORAGE_DATA_DIR": _r23_tmp}):
            from importlib import reload
            import agents.mcp_client as _mcp_mod
            _r23_client = _mcp_mod.MCPStorageClient(
                storage_url="http://localhost:19999",  # unreachable
            )
            versions = _r23_client.list_versions(limit=5, status_filter="all")
        test(
            "R2-3 functional: list_versions returns list (fallback path)",
            isinstance(versions, list),
            f"got type={type(versions).__name__}",
        )
    finally:
        _sh.rmtree(_r23_tmp, ignore_errors=True)
except Exception as e:
    test(f"R2-3 functional (skipped — {e})", False)


# ============================================================================
# R2-4 (P2): MCPDeployClient and MCPMonitorClient classes added
# ============================================================================
print("\n--- R2-4 (P2): MCPDeployClient and MCPMonitorClient classes ---")

test(
    "R2-4 MCPDeployClient class defined in mcp_client.py",
    "class MCPDeployClient" in mcp_client_source,
)
test(
    "R2-4 MCPMonitorClient class defined in mcp_client.py",
    "class MCPMonitorClient" in mcp_client_source,
)
test(
    "R2-4 MCPDeployClient has deploy_version method",
    "def deploy_version(" in mcp_client_source,
)
test(
    "R2-4 MCPDeployClient has rollback_version method",
    "def rollback_version(" in mcp_client_source,
)
test(
    "R2-4 MCPMonitorClient has push_metric method",
    "def push_metric(" in mcp_client_source,
)
test(
    "R2-4 MCPMonitorClient has write_log method",
    "def write_log(" in mcp_client_source,
)
test(
    "R2-4 both clients have MCP-first + fallback pattern",
    mcp_client_source.count("_get_fallback_backend") >= 3,  # storage + deploy + monitor
    f"_get_fallback_backend count={mcp_client_source.count('_get_fallback_backend')}",
)

# Functional: instantiate both new clients
try:
    from agents.mcp_client import MCPDeployClient, MCPMonitorClient

    deploy_client = MCPDeployClient(deploy_url="http://localhost:19998")
    monitor_client = MCPMonitorClient(monitor_url="http://localhost:19997")
    test(
        "R2-4 functional: MCPDeployClient instantiates",
        deploy_client is not None,
    )
    test(
        "R2-4 functional: MCPMonitorClient instantiates",
        monitor_client is not None,
    )
except Exception as e:
    for _ in range(2):
        test(f"R2-4 functional (skipped — {e})", False)


# ============================================================================
# R2-5 (P2): Decision agent routes through MCP clients, not direct backends
# ============================================================================
print("\n--- R2-5 (P2): Decision agent uses MCPDeployClient / MCPMonitorClient ---")

decision_source = (
    PROJECT_ROOT / "agents" / "decision" / "agent.py"
).read_text(encoding="utf-8")

test(
    "R2-5 Decision agent does not directly import LocalDeployBackend",
    "deploy_backend" not in decision_source and "import LocalDeployBackend" not in decision_source,
)
test(
    "R2-5 Decision agent does not directly import LocalMonitorBackend",
    "monitor_backend" not in decision_source and "import LocalMonitorBackend" not in decision_source,
)
test(
    "R2-5 Decision agent imports MCPDeployClient",
    "MCPDeployClient" in decision_source,
)
test(
    "R2-5 Decision agent imports MCPMonitorClient",
    "MCPMonitorClient" in decision_source,
)
test(
    "R2-5 execute_action uses MCPDeployClient().deploy_version",
    "MCPDeployClient()" in decision_source
    and "deploy_version" in decision_source,
)
test(
    "R2-5 execute_action uses MCPDeployClient().rollback_version",
    "rollback_version" in decision_source,
)
test(
    "R2-5 log_decision uses MCPMonitorClient().push_metric",
    "MCPMonitorClient()" in decision_source
    and "push_metric" in decision_source,
)
test(
    "R2-5 log_decision uses MCPMonitorClient().write_log",
    "write_log" in decision_source,
)


# ============================================================================
# R2-6 (P2): eval-datasets/ classified as relevant in parse_change
# ============================================================================
print("\n--- R2-6 (P2): eval-datasets/ relevant in parse_change ---")

test(
    "R2-6 orchestrator source has eval-datasets/ in relevance filter",
    'f.startswith("eval-datasets/")' in orch_source_r2
    or "startswith('eval-datasets/')" in orch_source_r2,
)

# Functional: parse_change with eval-datasets/... file
try:
    from agents.orchestrator.agent import parse_change as _parse_change

    # parse_change reads changed_files from webhook_payload.commits (not state key)
    only_eval_dataset = _parse_change({
        "trigger_type": "push",
        "webhook_payload": {
            "commits": [{"added": ["eval-datasets/baseline_v2.json"],
                         "modified": [], "removed": []}],
            "after": "abc12345",
            "ref": "refs/heads/main",
        },
        "errors": [],
    })
    test(
        "R2-6 functional: eval-datasets/ file is NOT 'irrelevant'",
        only_eval_dataset.get("change_type") != "irrelevant",
        f"got change_type={only_eval_dataset.get('change_type')}",
    )

    docs_only = _parse_change({
        "trigger_type": "push",
        "webhook_payload": {
            "commits": [{"added": ["docs/readme.md"],
                         "modified": [], "removed": []}],
            "after": "abc12346",
            "ref": "refs/heads/main",
        },
        "errors": [],
    })
    test(
        "R2-6 functional: docs/ file IS still 'irrelevant'",
        docs_only.get("change_type") == "irrelevant",
        f"got change_type={docs_only.get('change_type')}",
    )
except Exception as e:
    for _ in range(2):
        test(f"R2-6 functional (skipped — {e})", False)


# ============================================================================
# R2-7 (P2): /translate endpoint wraps blocking Gemini call in asyncio.to_thread
# ============================================================================
print("\n--- R2-7 (P2): /translate endpoint non-blocking ---")

# Count occurrences of asyncio.to_thread in app.py
to_thread_count = app_source.count("asyncio.to_thread")
test(
    "R2-7 /translate uses asyncio.to_thread (at least 2 occurrences in app.py)",
    to_thread_count >= 2,
    f"Found {to_thread_count} asyncio.to_thread call(s); need one for /batch and one for /translate",
)

# The /translate route itself must await asyncio.to_thread
# Look for the pattern inside the translate route definition
translate_route = ""
if "async def translate(" in app_source:
    start = app_source.index("async def translate(")
    # read up to the next route definition or end of function
    end = app_source.find("\n@app.", start + 1)
    if end == -1:
        end = len(app_source)
    translate_route = app_source[start:end]

test(
    "R2-7 translate route contains asyncio.to_thread",
    "asyncio.to_thread" in translate_route,
    "The translate route does not contain asyncio.to_thread",
)
test(
    "R2-7 translate route awaits asyncio.to_thread",
    "await asyncio.to_thread" in translate_route,
    "Missing 'await asyncio.to_thread' inside translate route",
)


# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 60)
total = _pass_count + _fail_count
if _fail_count == 0:
    print(f"ALL REVIEW-FIX TESTS PASSED: {_pass_count}/{total}")
else:
    print(f"TESTS: {_pass_count} passed, {_fail_count} FAILED (total: {total})")
print("=" * 60)

sys.exit(0 if _fail_count == 0 else 1)
